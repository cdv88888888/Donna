"""Scheduling skill — Donna watches the calendar and, per your setup, may act
on it automatically (CALENDAR_AUTONOMY=auto).

Right now she detects same-day conflicts and surfaces a resolution as an Item.
Actual auto-moves happen only when you approve the suggestion (or, if you later
set full calendar autonomy, immediately) — moving someone's meeting silently is
exactly the kind of thing that erodes trust, so it stays a suggestion by default.
"""
from __future__ import annotations

import datetime as dt

from ..config import settings
from ..db import Item, ItemStatus, Priority, Source, session_scope
from ..integrations import gcal


def scan_conflicts() -> dict:
    events = gcal.list_events()
    conflicts = gcal.find_conflicts(events)
    created = 0
    with session_scope() as s:
        for a, b in conflicts:
            ext = f"conflict:{a.id}:{b.id}"
            if s.query(Item).filter(Item.external_id == ext).first():
                continue
            s.add(Item(
                source=Source.calendar,
                external_id=ext,
                subject=f"Conflict: “{a.summary}” overlaps “{b.summary}”",
                snippet=(f"{a.summary} ({a.start:%H:%M}–{a.end:%H:%M}) overlaps "
                         f"{b.summary} ({b.start:%H:%M}–{b.end:%H:%M})."),
                priority=Priority.high,
                reason="Two meetings overlap",
                status=ItemStatus.open,
            ))
            created += 1
    return {"conflicts": len(conflicts), "new": created}


def confirm_event(event_id: str, new_start: dt.datetime, minutes: int = 30) -> None:
    """Apply a reschedule the owner approved."""
    gcal.move_event(event_id, new_start, new_start + dt.timedelta(minutes=minutes))
