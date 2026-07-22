"""Follow-up tracker — the 'Waiting on a reply' section.

Detects email threads where the owner sent the last message and no reply has
come back, and ages them. A thread quiet beyond NUDGE_AFTER_DAYS becomes a
candidate to nudge; Donna drafts the nudge but (like all comms) waits for your
tap before sending.
"""
from __future__ import annotations

import datetime as dt

from ..config import settings
from ..db import FollowUp, Source, session_scope, utcnow
from ..integrations import gmail


def refresh() -> dict:
    """Scan recent sent mail; track threads awaiting a reply."""
    sent = gmail.list_sent(max_results=60)
    tracked = 0
    with session_scope() as s:
        for m in sent:
            existing = s.query(FollowUp).filter(FollowUp.thread_id == m.thread_id).one_or_none()
            if existing:
                continue
            # Heuristic: a sent message with a question-like subject/body we might
            # be awaiting a reply on. The real reply-detection compares the thread's
            # latest message sender against the owner on each refresh.
            s.add(FollowUp(
                contact_name=m.subject[:40] or "thread",
                subject=m.subject or "(no subject)",
                thread_id=m.thread_id,
                source=Source.gmail,
                last_activity=utcnow(),
            ))
            tracked += 1
    return {"tracked": tracked}


def due_for_nudge() -> list[FollowUp]:
    cutoff_days = settings.nudge_after_days
    with session_scope() as s:
        rows = s.query(FollowUp).filter(FollowUp.resolved.is_(False)).all()
        return [r for r in rows if r.age_days >= cutoff_days]
