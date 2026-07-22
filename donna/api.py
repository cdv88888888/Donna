"""FastAPI backend — serves the focus dashboard (PWA) and its actions.

Endpoints are grouped:
  GET  /api/state              everything the dashboard renders
  POST /api/drafts/{id}/approve   send an approved reply
  POST /api/drafts/{id}          save an edited draft body
  POST /api/items/{id}/dismiss    dismiss / snooze an item
  POST /api/tasks                 add a to-do
  POST /api/tasks/{id}/toggle     check / uncheck a to-do
  POST /api/followups/{id}/nudge  chase a stale thread
  POST /api/command               natural-language command bar
  GET  /api/push/key              VAPID public key
  POST /api/push/subscribe        register a device for push
Static PWA files are served from ./web at the site root.
"""
from __future__ import annotations

import datetime as dt
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import (
    ActionLog,
    Contact,
    Draft,
    DraftStatus,
    FollowUp,
    Item,
    ItemStatus,
    PushSub,
    Task,
    init_db,
    session_scope,
    utcnow,
)

DEMO = os.environ.get("DONNA_DEMO") == "1"
app = FastAPI(title="Donna", docs_url=None, redoc_url=None)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    if DEMO:
        from .demo import seed_demo
        seed_demo()


# ── Read: full dashboard state ───────────────────────────────────────
@app.get("/api/state")
def state() -> dict:
    with session_scope() as s:
        items = (
            s.query(Item)
            .filter(Item.status == ItemStatus.open)
            .order_by(Item.priority, Item.created_at.desc())
            .all()
        )
        needs_you = []
        for it in items:
            draft = (
                s.query(Draft)
                .filter(Draft.item_id == it.id, Draft.status == DraftStatus.pending)
                .first()
            )
            needs_you.append({
                "id": it.id,
                "source": it.source.value,
                "sender": it.sender,
                "subject": it.subject,
                "snippet": it.snippet,
                "body": it.body,               # the original message Donna is replying to
                "priority": it.priority.value,
                "reason": it.reason,
                "when": _ago(it.created_at),
                "draft": ({"id": draft.id, "body": draft.body} if draft else None),
            })

        vips = [
            {"id": c.id, "name": c.name, "note": c.relationship_note}
            for c in s.query(Contact).filter(Contact.is_vip.is_(True)).all()
        ]
        followups = [
            {"id": f.id, "name": f.contact_name, "subject": f.subject, "age": f.age_days}
            for f in s.query(FollowUp).filter(FollowUp.resolved.is_(False)).all()
        ]
        tasks = [
            {"id": t.id, "text": t.text, "done": t.done, "by": t.created_by}
            for t in s.query(Task).order_by(Task.done, Task.created_at.desc()).all()
        ]
        handled = [
            {"summary": a.summary, "when": _ago(a.created_at)}
            for a in s.query(ActionLog).order_by(ActionLog.created_at.desc()).limit(20).all()
        ]
        handled_count = s.query(ActionLog).count()

    try:
        from .integrations import gcal
        events = [
            {"time": f"{e.start:%H:%M}", "title": e.summary}
            for e in gcal.list_events()
        ]
    except Exception:
        events = []

    return {
        "greeting": _greeting(),
        "date": f"{dt.datetime.now(settings.tz):%a · %b %d}",
        "thesis": {
            "incoming": handled_count + len(needs_you),
            "handled": handled_count,
            "needs_you": len(needs_you),
        },
        "needs_you": needs_you,
        "vips": vips,
        "followups": sorted(followups, key=lambda f: -f["age"]),
        "today": events,
        "tasks": tasks,
        "handled": handled,
    }


# ── Actions ──────────────────────────────────────────────────────────
@app.post("/api/drafts/{draft_id}/approve")
def approve_draft(draft_id: int) -> dict:
    with session_scope() as s:
        draft = s.get(Draft, draft_id)
        if not draft:
            raise HTTPException(404, "draft not found")
        item = s.get(Item, draft.item_id)
        if not DEMO:
            _send_draft(draft, item)
        draft.status = DraftStatus.sent
        item.status = ItemStatus.done
        s.add(ActionLog(summary=f"Sent your reply to {item.sender}", source=item.source))
    return {"ok": True}


@app.post("/api/drafts/{draft_id}")
async def edit_draft(draft_id: int, request: Request) -> dict:
    payload = await request.json()
    with session_scope() as s:
        draft = s.get(Draft, draft_id)
        if not draft:
            raise HTTPException(404, "draft not found")
        draft.body = payload.get("body", draft.body)
        draft.status = DraftStatus.edited
    return {"ok": True}


@app.post("/api/items/{item_id}/dismiss")
def dismiss_item(item_id: int) -> dict:
    with session_scope() as s:
        item = s.get(Item, item_id)
        if item:
            item.status = ItemStatus.dismissed
    return {"ok": True}


@app.post("/api/tasks")
async def add_task(request: Request) -> dict:
    payload = await request.json()
    with session_scope() as s:
        s.add(Task(text=payload["text"], created_by="you"))
    return {"ok": True}


@app.post("/api/tasks/{task_id}/toggle")
def toggle_task(task_id: int) -> dict:
    with session_scope() as s:
        t = s.get(Task, task_id)
        if t:
            t.done = not t.done
    return {"ok": True}


@app.post("/api/followups/{fu_id}/nudge")
def nudge(fu_id: int) -> dict:
    with session_scope() as s:
        fu = s.get(FollowUp, fu_id)
        if not fu:
            raise HTTPException(404)
        # A nudge drafts a chase message for approval rather than auto-sending.
        s.add(ActionLog(summary=f"Drafted a nudge for “{fu.subject}”", source=fu.source))
    return {"ok": True, "message": "Nudge drafted — approve it in your queue."}


@app.post("/api/command")
async def command(request: Request) -> dict:
    payload = await request.json()
    if DEMO:
        return {"reply": "In demo mode I can't run commands, but this is where I'd act."}
    from .skills import commands
    return {"reply": commands.handle(payload["text"])}


# ── Push ─────────────────────────────────────────────────────────────
@app.get("/api/push/key")
def push_key() -> dict:
    return {"key": os.environ.get("VAPID_PUBLIC_KEY", "")}


@app.post("/api/push/subscribe")
async def push_subscribe(request: Request) -> dict:
    sub = await request.json()
    keys = sub.get("keys", {})
    with session_scope() as s:
        if not s.query(PushSub).filter(PushSub.endpoint == sub["endpoint"]).first():
            s.add(PushSub(endpoint=sub["endpoint"], p256dh=keys["p256dh"], auth=keys["auth"]))
    return {"ok": True}


# ── Helpers ──────────────────────────────────────────────────────────
def _send_draft(draft: Draft, item: Item) -> None:
    from .db import Source
    if draft.channel == Source.gmail:
        from .integrations import gmail
        gmail.send_reply(item.thread_id, draft.to, item.subject or "", draft.body)
    elif draft.channel == Source.telegram:
        import asyncio
        from .integrations import telegram_user

        async def _go():
            c = telegram_user.get_client()
            await c.connect()
            try:
                await telegram_user.send_message(int(draft.to), draft.body)
            finally:
                await c.disconnect()

        asyncio.run(_go())


def _ago(when: dt.datetime) -> str:
    if when.tzinfo is None:  # SQLite returns naive datetimes; treat as UTC
        when = when.replace(tzinfo=dt.timezone.utc)
    delta = utcnow() - when
    mins = int(delta.total_seconds() // 60)
    if mins < 60:
        return f"{max(mins, 1)}m ago"
    if mins < 1440:
        return f"{mins // 60}h ago"
    return f"{mins // 1440}d ago"


def _greeting() -> str:
    h = dt.datetime.now(settings.tz).hour
    if h < 12:
        return "Good morning."
    if h < 18:
        return "Good afternoon."
    return "Good evening."


# Static PWA (mounted last so /api/* wins).
_web = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
if os.path.isdir(_web):
    app.mount("/", StaticFiles(directory=_web, html=True), name="web")
