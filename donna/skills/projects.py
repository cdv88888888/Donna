"""Projects — auto-group messages across sources into things the owner is working on.

Two entry points:
  backfill()        one-time (or periodic) deep scan: cluster recent Gmail +
                    Telegram + Calendar into projects via the brain.
  assign_item(item) live: attach a newly-triaged item to an existing project
                    (or leave it loose). Called from the ingest pipeline.

Plus recompute_status(), run on a schedule, which sets each project to
needs_you / stalled / on_track and powers the proactive nudges & alerts.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Optional

from ..config import settings
from ..db import (
    Item,
    ItemStatus,
    Project,
    ProjectItem,
    ProjectStatus,
    Source,
    session_scope,
    utcnow,
)
from .. import brain


# ── Status ───────────────────────────────────────────────────────────
def recompute_status(s, project: Project) -> None:
    """Set a project's status from its open items, deadline, and quiet time."""
    open_items = (
        s.query(Item)
        .filter(Item.project_id == project.id, Item.status == ItemStatus.open)
        .count()
    )
    deadline_risk = False
    if project.deadline:
        dl = project.deadline
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=dt.timezone.utc)
        deadline_risk = 0 <= (dl - utcnow()).days <= 3

    if open_items or deadline_risk:
        project.status = ProjectStatus.needs_you
    elif project.age_days >= settings.nudge_after_days:
        project.status = ProjectStatus.stalled
    else:
        project.status = ProjectStatus.on_track


def recompute_all_status() -> dict:
    with session_scope() as s:
        for p in s.query(Project).filter(Project.dismissed.is_(False)).all():
            recompute_status(s, p)
    return {"ok": True}


# ── Live assignment ──────────────────────────────────────────────────
def _match(project: Project, sender: str, subject: str, body: str) -> bool:
    hay = f"{sender} {subject} {body}".lower()
    if project.company and project.company.lower() in hay:
        return True
    return any(k and k.lower() in hay for k in (project.match_keys or []))


def assign_item(item_id: int) -> Optional[int]:
    """Attach an open Item to the best-matching project. Returns project id or None."""
    with session_scope() as s:
        item = s.get(Item, item_id)
        if not item:
            return None
        text = f"{item.snippet or ''} {item.body or ''}"
        for p in s.query(Project).filter(Project.dismissed.is_(False)).all():
            if _match(p, item.sender or "", item.subject or "", text):
                item.project_id = p.id
                _touch(s, p, item.source, item.external_id, item.subject)
                recompute_status(s, p)
                return p.id
    return None


def _touch(s, project: Project, source: Source, external_id: str, label: Optional[str]) -> None:
    project.last_activity = utcnow()
    exists = (
        s.query(ProjectItem)
        .filter(ProjectItem.source == source, ProjectItem.external_id == external_id)
        .first()
    )
    if not exists:
        s.add(ProjectItem(project_id=project.id, source=source,
                          external_id=external_id, label=(label or "")[:300]))


# ── Backfill / clustering ────────────────────────────────────────────
def _parse_deadline(value) -> Optional[dt.datetime]:
    if not value or value in ("null", "None"):
        return None
    try:
        return dt.datetime.fromisoformat(str(value)[:10]).replace(tzinfo=settings.tz)
    except Exception:
        return None


def _gather() -> list[dict]:
    """Collect recent messages/events across sources as {id, source, external_id, summary}."""
    from ..integrations import gmail, gcal, telegram_user

    rows: list[dict] = []
    nid = 0

    try:
        for m in gmail.fetch_unread(max_results=40) + gmail.list_sent(max_results=40):
            nid += 1
            rows.append({"id": nid, "source": "gmail", "external_id": m.id,
                         "summary": f"[email] from {m.sender} — {m.subject}: {m.snippet or m.body[:160]}"})
    except Exception:
        pass

    try:
        events = gcal.list_events()
        for e in events:
            nid += 1
            rows.append({"id": nid, "source": "calendar", "external_id": e.id,
                         "summary": f"[event] {e.start:%b %d %H:%M} {e.summary} with {', '.join(e.attendees[:3])}"})
    except Exception:
        pass

    try:
        async def _tg():
            c = telegram_user.get_client()
            await c.connect()
            try:
                return await telegram_user.fetch_history(limit_per_chat=25, max_chats=20)
            finally:
                await c.disconnect()
        for m in asyncio.run(_tg()):
            nid += 1
            rows.append({"id": nid, "source": "telegram", "external_id": f"{m.chat_id}:{m.id}",
                         "summary": f"[telegram] {m.sender_name}: {m.text[:160]}"})
    except Exception:
        pass

    return rows


_DONE_WORDS = {"done", "approved", "proceed", "completed", "paid", "closed", "resolved", "sent"}


def sync_monday() -> dict:
    """Turn each configured Monday board into a live project card."""
    from ..integrations import monday

    boards = monday.fetch_boards()
    if not boards:
        return {"boards": 0, "note": "no Monday token/boards configured"}

    synced = 0
    with session_scope() as s:
        for b in boards:
            pending = [
                it for it in b.items
                if not any(w in (it.status or it.group).lower() for w in _DONE_WORDS)
            ]
            ref = f"monday:board:{b.id}"
            p = s.query(Project).filter(Project.external_ref == ref).one_or_none()
            if not p:
                p = Project(name=b.name, created_by="monday", external_ref=ref,
                            match_keys=[b.name])
                s.add(p)
                s.flush()
            p.pending = len(pending)
            p.next_action = (
                f"{len(pending)} item(s) need attention on the {b.name} board."
                if pending else f"All items on {b.name} are handled."
            )
            p.status = ProjectStatus.needs_you if pending else ProjectStatus.on_track
            p.last_activity = utcnow()
            _touch(s, p, Source.monday, f"board:{b.id}", b.name)
            synced += 1
    return {"boards": len(boards), "synced": synced}


def backfill() -> dict:
    """Scan recent history and (re)build projects. Auto-creates per the owner's setting."""
    rows = _gather()
    if not rows:
        return {"scanned": 0, "created": 0, "note": "no source data (connect Gmail/Telegram first)"}

    by_id = {r["id"]: r for r in rows}
    corpus = "\n".join(f'{r["id"]}. {r["summary"]}' for r in rows)[:24000]
    clusters = brain.cluster_projects(corpus)

    created = 0
    with session_scope() as s:
        for c in clusters:
            members = [by_id[i] for i in c.get("member_ids", []) if i in by_id]
            if not members:
                continue
            p = Project(
                name=c.get("name", "Untitled project")[:300],
                company=(c.get("company") or None),
                next_action=c.get("next_action"),
                owes=(c.get("owes") or None),
                amount=(c.get("amount") or None),
                deadline=_parse_deadline(c.get("deadline")),
                participants=c.get("participants", []),
                match_keys=c.get("match_keys", []),
                created_by="donna",
                last_activity=utcnow(),
            )
            s.add(p)
            s.flush()
            for m in members:
                _touch(s, p, Source(m["source"]), m["external_id"], m["summary"][:300])
            recompute_status(s, p)
            created += 1
    return {"scanned": len(rows), "clusters": len(clusters), "created": created}
