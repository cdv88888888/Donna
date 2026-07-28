"""Morning brief — the one-paragraph 'here's your day' Donna sends at BRIEF_TIME.

It reads the current dashboard state (open items, today's calendar, follow-ups,
tasks) and has the brain write it in Donna's warm, concise voice, then pushes it
to your phone.
"""
from __future__ import annotations

import datetime as dt

from ..config import settings
from ..db import FollowUp, Item, ItemStatus, Task, session_scope
from ..integrations import gcal
from .. import brain, notify

BRIEF_SYSTEM = """You are Donna, {owner}'s executive assistant, writing a short \
morning brief. Warm, calm, concise — three or four sentences max. Lead with what \
needs them today, mention the calendar shape, and end with one grounding line. \
No bullet lists, no greeting header. Sound like a sharp, trusted human EA."""


def compose() -> str:
    with session_scope() as s:
        open_items = s.query(Item).filter(Item.status == ItemStatus.open).all()
        tasks = s.query(Task).filter(Task.done.is_(False)).all()
        followups = s.query(FollowUp).filter(FollowUp.resolved.is_(False)).all()
        needs = [f"- {i.subject} ({i.priority.value})" for i in open_items[:8]]
        stale = [f.subject for f in followups if f.age_days >= settings.nudge_after_days]

    try:
        events = gcal.list_events()
        agenda = [f"- {e.start:%H:%M} {e.summary}" for e in events]
    except Exception:
        agenda = ["(calendar unavailable)"]

    facts = (
        f"Date: {dt.datetime.now(settings.tz):%A, %B %d}\n"
        f"Needs you ({len(needs)}):\n" + ("\n".join(needs) or "- nothing") + "\n\n"
        f"Today's calendar:\n" + ("\n".join(agenda) or "- clear") + "\n\n"
        f"Open tasks: {len(tasks)}\n"
        f"Stale follow-ups: {len(stale)}"
    )
    return brain.ask(
        system=BRIEF_SYSTEM.format(owner=settings.owner_name),
        user=facts,
        max_tokens=400,
    ).strip()


def send_brief() -> str:
    text = compose()
    notify.push("☀️ Your morning brief", text[:180], url="/")
    return text
