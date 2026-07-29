"""Entry point — runs everything in one asyncio process:

  • the FastAPI app (dashboard + API), served by uvicorn
  • the APScheduler proactive loops
  • the live Telethon listener for incoming Telegram DMs

Run locally:   python -m donna.main
In production:  the Dockerfile / Procfile calls this.
Demo (no keys): DONNA_DEMO=1 python -m donna.main
"""
from __future__ import annotations

import logging
import os

import uvicorn

from .api import app
from .config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
)
log = logging.getLogger("donna")

DEMO = os.environ.get("DONNA_DEMO") == "1"


@app.on_event("startup")
async def _start_background() -> None:
    if DEMO:
        log.info("DEMO mode — proactive loops and Telegram listener are OFF.")
        return

    # Proactive scheduler
    from .scheduler import build_scheduler
    sched = build_scheduler()
    sched.start()
    app.state.scheduler = sched
    log.info("Scheduler started (inbox every %sm, brief at %s).",
             settings.inbox_poll_minutes, settings.brief_time)

    # Live Telegram listener
    if settings.telegram_session:
        try:
            import asyncio

            from .integrations import telegram_user
            from .skills import ingest, stash
            from .notify import push_if_urgent

            async def _on_dm(msg) -> None:
                result = ingest.process_telegram(msg)
                if result.get("needs_you") and result.get("priority") in ("urgent", "high"):
                    push_if_urgent(f"Telegram: {msg.sender_name}", msg.text[:80])

            async def _on_saved(msg) -> None:
                # Anything the owner drops in Saved Messages is a stash capture.
                # Classification is a blocking API call, so it goes to a thread
                # rather than stalling the listener.
                result = await asyncio.to_thread(stash.capture_telegram, msg)
                if result.get("reply"):
                    # Donna answers in the same chat — that's what makes
                    # "forward → get asked → reply" one continuous exchange.
                    await telegram_user.send_message(msg.chat_id, result["reply"])

            client = telegram_user.get_client()
            telegram_user.on_new_dm(_on_dm)
            telegram_user.on_saved_message(_on_saved)
            await client.connect()
            app.state.telegram = client
            log.info("Telegram listener connected (DMs + Saved Messages).")
        except Exception:
            log.exception("Telegram listener failed to start (continuing without it).")
    else:
        log.info("No TELEGRAM_SESSION set — Telegram listener disabled.")


@app.on_event("shutdown")
async def _stop_background() -> None:
    sched = getattr(app.state, "scheduler", None)
    if sched:
        sched.shutdown(wait=False)
    client = getattr(app.state, "telegram", None)
    if client:
        await client.disconnect()


def run() -> None:
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    run()
