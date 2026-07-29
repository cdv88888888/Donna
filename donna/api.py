"""FastAPI backend — serves the focus dashboard (PWA) and its actions.

Endpoints are grouped:
  GET  /api/state              everything the dashboard renders
  POST /api/drafts/{id}/approve   send an approved reply
  POST /api/drafts/{id}          save an edited draft body
  POST /api/items/{id}/dismiss    dismiss / snooze an item
  POST /api/tasks                 add a to-do
  POST /api/tasks/{id}/toggle     check / uncheck a to-do
  POST /api/followups/{id}/nudge  chase a stale thread
  GET  /api/stash                 the stash: buckets, items, open questions
  POST /api/stash/capture         paste a link in by hand
  POST /api/stash/{id}/answer     tell Donna what an unsorted item is
  POST /api/stash/{id}/kind       file it yourself
  POST /api/stash/{id}/tried      verdict + archive
  POST /api/stash/proposals/{id}  accept / reject a sub-folder split
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
    Bucket,
    BucketProposal,
    Contact,
    Draft,
    DraftStatus,
    FollowUp,
    Item,
    ItemStatus,
    Priority,
    Project,
    ProjectItem,
    ProjectStatus,
    PushSub,
    StashItem,
    StashKind,
    StashStatus,
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
        # Open items, plus snoozed ones whose "later" has arrived.
        now = utcnow()
        candidates = (
            s.query(Item)
            .filter(
                (Item.status == ItemStatus.open)
                | ((Item.status == ItemStatus.snoozed) & (Item.snooze_until <= now))
            )
            .all()
        )
        # Sort by real severity (urgent first), then newest — enum sorts
        # alphabetically in SQL, which would bury urgent, so we rank here.
        rank = {Priority.urgent: 0, Priority.high: 1, Priority.normal: 2, Priority.low: 3}
        candidates.sort(key=lambda it: (rank.get(it.priority, 9), -it.id))
        items = candidates
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
                "draft": ({"id": draft.id, "body": draft.body,
                           "summary": draft.summary} if draft else None),
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


# ── Projects ─────────────────────────────────────────────────────────
_SRC_ICON = {"gmail": "✉", "telegram": "✈", "calendar": "◷", "monday": "⬡",
             "web": "⌘", "system": "•"}


@app.get("/api/projects")
def projects() -> dict:
    order = {ProjectStatus.needs_you: 0, ProjectStatus.stalled: 1, ProjectStatus.on_track: 2}
    with session_scope() as s:
        rows = s.query(Project).filter(Project.dismissed.is_(False)).all()
        rows.sort(key=lambda p: (order.get(p.status, 9), -p.id))
        out = []
        for p in rows:
            members = s.query(ProjectItem).filter(ProjectItem.project_id == p.id).all()
            counts: dict[str, int] = {}
            for m in members:
                counts[m.source.value] = counts.get(m.source.value, 0) + 1
            src = " · ".join(f"{_SRC_ICON.get(k, '')} {v}" for k, v in counts.items())
            needs = (
                s.query(Item)
                .filter(Item.project_id == p.id, Item.status == ItemStatus.open)
                .count()
                + (p.pending or 0)   # external needs, e.g. pending Monday items
            )
            out.append({
                "id": p.id,
                "name": p.name,
                "company": p.company,
                "status": p.status.value,
                "next_action": p.next_action,
                "owes": p.owes,
                "amount": p.amount,
                "deadline": (f"Due {p.deadline:%b %d}" if p.deadline else None),
                "people": p.participants or [],
                "sources": src,
                "needs_you": needs,
                "created_by": p.created_by,
                "when": _ago(p.last_activity),
            })
        counts = {
            "active": len(rows),
            "needs_you": sum(1 for p in rows if p.status == ProjectStatus.needs_you),
            "stalled": sum(1 for p in rows if p.status == ProjectStatus.stalled),
        }
    return {"projects": out, "counts": counts}


@app.post("/api/projects/{project_id}/dismiss")
def dismiss_project(project_id: int) -> dict:
    with session_scope() as s:
        p = s.get(Project, project_id)
        if p:
            p.dismissed = True
    return {"ok": True}


@app.post("/api/projects/{project_id}/nudge")
def nudge_project(project_id: int) -> dict:
    with session_scope() as s:
        p = s.get(Project, project_id)
        if not p:
            raise HTTPException(404)
        s.add(ActionLog(summary=f"Drafted a nudge for project “{p.name}”"))
    return {"ok": True, "message": "Nudge drafted — approve it in your queue."}


@app.post("/api/projects/backfill")
def backfill_projects() -> dict:
    if DEMO:
        return {"note": "Demo mode — projects are pre-seeded."}
    from .skills import projects as proj
    return proj.backfill()


@app.post("/api/projects/sync-monday")
def sync_monday_projects() -> dict:
    if DEMO:
        return {"note": "Demo mode — a sample Monday project is pre-seeded."}
    from .skills import projects as proj
    return proj.sync_monday()


# ── Stash ────────────────────────────────────────────────────────────
_KIND_ORDER = [StashKind.tool, StashKind.inspo, StashKind.idea, StashKind.read]
_KIND_META = {
    StashKind.tool: ("Tools to try", "Forwarded, unopened, waiting on you to actually try it."),
    StashKind.inspo: ("Inspo", "Hooks, formats and edits worth stealing. No task attached."),
    StashKind.idea: ("Ideas", "Business thoughts to chew on when you have the room."),
    StashKind.read: ("Read later", "Long stuff you didn't have time for."),
}


def _stash_item(it: StashItem) -> dict:
    return {
        "id": it.id,
        "title": it.title or "(untitled)",
        "summary": it.summary,
        "why": it.why,
        "note": it.note,
        "url": it.url,
        "platform": it.platform,
        "kind": it.kind.value,
        "when": _ago(it.created_at),
        "has_task": it.task_id is not None,
    }


@app.get("/api/stash")
def stash_view() -> dict:
    with session_scope() as s:
        asking = [
            {**_stash_item(it), "question": it.question, "raw": it.raw_text}
            for it in s.query(StashItem)
            .filter(StashItem.status == StashStatus.asking)
            .order_by(StashItem.created_at.desc())
            .all()
        ]

        proposals = []
        for p in (
            s.query(BucketProposal).filter(BucketProposal.status == "pending").all()
        ):
            parent = s.get(Bucket, p.bucket_id)
            proposals.append({
                "id": p.id,
                "parent": parent.name if parent else "",
                "name": p.name,
                "rationale": p.rationale,
                "count": len(p.item_ids or []),
            })

        def _items_in(bucket_id: int) -> list[dict]:
            rows = (
                s.query(StashItem)
                .filter(StashItem.bucket_id == bucket_id,
                        StashItem.status == StashStatus.filed)
                .order_by(StashItem.created_at.desc())
                .all()
            )
            return [_stash_item(r) for r in rows]

        kinds = []
        for kind in _KIND_ORDER:
            topics = []
            tops = (
                s.query(Bucket)
                .filter(Bucket.kind == kind, Bucket.parent_id.is_(None))
                .order_by(Bucket.name)
                .all()
            )
            for b in tops:
                subs = [
                    {"id": c.id, "name": c.name, "items": _items_in(c.id)}
                    for c in s.query(Bucket)
                    .filter(Bucket.parent_id == b.id)
                    .order_by(Bucket.name)
                    .all()
                ]
                items = _items_in(b.id)
                if not items and not any(sub["items"] for sub in subs):
                    continue  # an empty folder is noise
                topics.append({"id": b.id, "name": b.name, "items": items, "subs": subs})
            label, blurb = _KIND_META[kind]
            kinds.append({"key": kind.value, "label": label, "blurb": blurb,
                          "topics": topics})

        tried = [
            {"id": it.id, "title": it.title, "verdict": it.verdict,
             "kind": it.kind.value, "url": it.url, "when": _ago(it.decided_at or it.created_at)}
            for it in s.query(StashItem)
            .filter(StashItem.status == StashStatus.tried)
            .order_by(StashItem.decided_at.desc())
            .limit(30)
            .all()
        ]

        counts = {
            "filed": s.query(StashItem).filter(StashItem.status == StashStatus.filed).count(),
            "asking": len(asking),
            "tools": s.query(StashItem)
            .filter(StashItem.status == StashStatus.filed,
                    StashItem.kind == StashKind.tool).count(),
            "tried": s.query(StashItem)
            .filter(StashItem.status == StashStatus.tried).count(),
        }

    return {"asking": asking, "proposals": proposals, "kinds": kinds,
            "tried": tried, "counts": counts}


@app.post("/api/stash/capture")
async def stash_capture(request: Request) -> dict:
    payload = await request.json()
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "nothing to stash")
    from .skills import stash
    return stash.capture_text(text)


@app.post("/api/stash/{item_id}/answer")
async def stash_answer(item_id: int, request: Request) -> dict:
    payload = await request.json()
    from .skills import stash
    return stash.answer(item_id, payload.get("note", ""))


@app.post("/api/stash/{item_id}/kind")
async def stash_set_kind(item_id: int, request: Request) -> dict:
    payload = await request.json()
    from .skills import stash
    return stash.set_kind(item_id, payload.get("kind", ""), payload.get("topic"))


@app.post("/api/stash/{item_id}/tried")
async def stash_tried(item_id: int, request: Request) -> dict:
    payload = await request.json()
    from .skills import stash
    return stash.mark_tried(item_id, payload.get("verdict", ""))


@app.post("/api/stash/{item_id}/archive")
def stash_archive(item_id: int) -> dict:
    from .skills import stash
    return stash.archive(item_id)


@app.post("/api/stash/proposals/{proposal_id}/accept")
def stash_accept(proposal_id: int) -> dict:
    from .skills import stash
    return stash.accept_proposal(proposal_id)


@app.post("/api/stash/proposals/{proposal_id}/reject")
def stash_reject(proposal_id: int) -> dict:
    from .skills import stash
    return stash.reject_proposal(proposal_id)


@app.post("/api/stash/organize")
def stash_organize() -> dict:
    """Run the split sweep now instead of waiting for the hourly job."""
    from .skills import stash
    return stash.sweep_splits()


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


@app.post("/api/drafts/approve_all")
def approve_all() -> dict:
    """Approve every pending draft in one tap (the routine replies)."""
    sent = 0
    with session_scope() as s:
        pending = s.query(Draft).filter(Draft.status == DraftStatus.pending).all()
        for draft in pending:
            item = s.get(Item, draft.item_id)
            if not DEMO:
                _send_draft(draft, item)
            draft.status = DraftStatus.sent
            item.status = ItemStatus.done
            s.add(ActionLog(summary=f"Sent your reply to {item.sender}", source=item.source))
            sent += 1
    return {"ok": True, "sent": sent}


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
    """Gone for good."""
    with session_scope() as s:
        item = s.get(Item, item_id)
        if item:
            item.status = ItemStatus.dismissed
    return {"ok": True}


@app.post("/api/items/{item_id}/snooze")
def snooze_item(item_id: int) -> dict:
    """Skip = bring it back later (default: in 4 hours)."""
    import datetime as _dt
    with session_scope() as s:
        item = s.get(Item, item_id)
        if item:
            item.status = ItemStatus.snoozed
            item.snooze_until = utcnow() + _dt.timedelta(hours=4)
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
