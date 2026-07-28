"""Google Calendar integration — read today's agenda, find conflicts,
create / move events. Calendar ops are the one area Donna is allowed to
act automatically (per your setup), so these are used directly by the
scheduling skill.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from googleapiclient.discovery import build

from ..config import settings
from .google_auth import load_credentials


@dataclass
class Event:
    id: str
    summary: str
    start: dt.datetime
    end: dt.datetime
    attendees: list[str]
    location: str = ""


def _service():
    return build("calendar", "v3", credentials=load_credentials(), cache_discovery=False)


def _parse(when: dict) -> dt.datetime:
    raw = when.get("dateTime") or when.get("date")
    if len(raw) == 10:  # all-day
        return dt.datetime.fromisoformat(raw).replace(tzinfo=settings.tz)
    return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))


def list_events(day: Optional[dt.date] = None) -> list[Event]:
    """Events for a given day (default: today in the owner's timezone)."""
    day = day or dt.datetime.now(settings.tz).date()
    start = dt.datetime.combine(day, dt.time.min, tzinfo=settings.tz)
    end = dt.datetime.combine(day, dt.time.max, tzinfo=settings.tz)
    resp = (
        _service().events()
        .list(
            calendarId="primary",
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    out: list[Event] = []
    for e in resp.get("items", []):
        if e.get("status") == "cancelled":
            continue
        out.append(
            Event(
                id=e["id"],
                summary=e.get("summary", "(no title)"),
                start=_parse(e["start"]),
                end=_parse(e["end"]),
                attendees=[a.get("email", "") for a in e.get("attendees", [])],
                location=e.get("location", ""),
            )
        )
    return out


def find_conflicts(events: list[Event]) -> list[tuple[Event, Event]]:
    """Pairs of events whose times overlap."""
    conflicts = []
    ordered = sorted(events, key=lambda e: e.start)
    for i in range(len(ordered) - 1):
        a, b = ordered[i], ordered[i + 1]
        if b.start < a.end:
            conflicts.append((a, b))
    return conflicts


def create_event(summary: str, start: dt.datetime, end: dt.datetime,
                 attendees: Optional[list[str]] = None, location: str = "") -> str:
    body = {
        "summary": summary,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "location": location,
    }
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    created = _service().events().insert(
        calendarId="primary", body=body, sendUpdates="all"
    ).execute()
    return created["id"]


def move_event(event_id: str, start: dt.datetime, end: dt.datetime) -> None:
    svc = _service()
    ev = svc.events().get(calendarId="primary", eventId=event_id).execute()
    ev["start"] = {"dateTime": start.isoformat()}
    ev["end"] = {"dateTime": end.isoformat()}
    svc.events().update(
        calendarId="primary", eventId=event_id, body=ev, sendUpdates="all"
    ).execute()
