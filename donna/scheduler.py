"""The proactive loops — what makes Donna *proactive* rather than reactive.

APScheduler runs four jobs:
  - inbox sweep         every INBOX_POLL_MINUTES
  - follow-up refresh   hourly
  - conflict scan       hourly
  - morning brief       once daily at BRIEF_TIME (owner timezone)

Plus a live Telethon handler for incoming Telegram DMs (real-time triage).
This module is started by main.py.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import settings

log = logging.getLogger("donna.scheduler")


def _run_inbox() -> None:
    from .skills import ingest
    try:
        summary = ingest.poll_inbox()
        log.info("inbox sweep: %s", summary)
    except Exception:
        log.exception("inbox sweep failed")


def _run_followups() -> None:
    from .skills import followups
    try:
        followups.refresh()
    except Exception:
        log.exception("follow-up refresh failed")


def _run_conflicts() -> None:
    from .skills import scheduling
    try:
        scheduling.scan_conflicts()
    except Exception:
        log.exception("conflict scan failed")


def _run_projects() -> None:
    from .skills import projects
    try:
        projects.sync_monday()            # refresh Monday boards (no-op if unconfigured)
        projects.recompute_all_status()   # stalled / deadline-risk / needs-you upkeep
    except Exception:
        log.exception("project status upkeep failed")


def _run_brief() -> None:
    from .skills import brief
    try:
        brief.send_brief()
        log.info("morning brief sent")
    except Exception:
        log.exception("morning brief failed")


def build_scheduler() -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=str(settings.tz))
    sched.add_job(_run_inbox, IntervalTrigger(minutes=settings.inbox_poll_minutes),
                  id="inbox", max_instances=1, coalesce=True)
    sched.add_job(_run_followups, IntervalTrigger(hours=1), id="followups")
    sched.add_job(_run_conflicts, IntervalTrigger(hours=1), id="conflicts")
    sched.add_job(_run_projects, IntervalTrigger(hours=1), id="projects")
    hour, minute = settings.brief_hour_minute
    sched.add_job(_run_brief, CronTrigger(hour=hour, minute=minute), id="brief")
    return sched
