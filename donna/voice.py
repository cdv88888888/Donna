"""Voice training — learn how the owner actually writes.

We pull real sent messages (Gmail sent-mail + Telegram outgoing), ask Claude to
distill a reusable style guide, and keep a handful of raw examples for few-shot
grounding. The result is stored per channel and injected into every draft, so
Donna's replies sound like the owner and get better as more data accrues.
"""
from __future__ import annotations

import asyncio

from .brain import ask
from .config import settings
from .db import StyleProfile, session_scope, utcnow

DISTILL_SYSTEM = """You are analyzing how a specific person writes so their \
assistant can imitate them. Read the real messages below and produce a precise, \
practical STYLE GUIDE another writer could follow to be mistaken for this person.

Cover: typical greeting and sign-off; sentence length and formality; warmth; \
directness; punctuation and capitalization quirks; emoji usage; any language \
mixing (e.g. Taglish) and when each language appears; recurring phrases; how they \
say yes/no/maybe; how they handle requests they decline.

Be specific and concrete. Output the guide as tight bullet points, no preamble."""


def _distill(channel: str, samples: list[str]) -> str:
    corpus = "\n\n---\n\n".join(s.strip() for s in samples if s.strip())[:24000]
    guide = ask(
        system=DISTILL_SYSTEM,
        user=f"Channel: {channel}\nHere are real messages this person sent:\n\n{corpus}",
        model=settings.model_draft,
        max_tokens=1200,
    )
    return guide.strip()


def _save(channel: str, guide: str, examples: list[str]) -> None:
    with session_scope() as s:
        row = s.query(StyleProfile).filter_by(channel=channel).one_or_none()
        if row:
            row.guide, row.examples, row.updated_at = guide, examples[:8], utcnow()
        else:
            s.add(StyleProfile(channel=channel, guide=guide, examples=examples[:8]))


def train_email(max_messages: int = 200) -> str:
    from .integrations import gmail

    sent = gmail.list_sent(max_results=max_messages)
    samples = [m.body for m in sent if 20 < len(m.body) < 4000]
    if not samples:
        return "No email samples found to train on."
    guide = _distill("email", samples)
    _save("email", guide, samples[:8])
    return f"Trained email voice on {len(samples)} messages."


def train_telegram(max_messages: int = 800) -> str:
    from .integrations import telegram_user

    async def _run():
        client = telegram_user.get_client()
        await client.connect()
        try:
            return await telegram_user.fetch_history()
        finally:
            await client.disconnect()

    msgs = asyncio.run(_run())
    samples = [m.text for m in msgs if 3 < len(m.text) < 1000][:max_messages]
    if not samples:
        return "No Telegram samples found to train on."
    guide = _distill("telegram", samples)
    _save("telegram", guide, samples[:8])
    return f"Trained Telegram voice on {len(samples)} messages."


def build_global_profile() -> str:
    """Merge per-channel guides into a general one used when channel is unknown."""
    with session_scope() as s:
        guides = {p.channel: p.guide for p in s.query(StyleProfile).all()
                  if p.channel in ("email", "telegram")}
    if not guides:
        return "Nothing to merge yet."
    merged = ask(
        system="Merge these per-channel writing style guides for one person into a "
        "single general voice guide. Keep channel-specific notes labeled. Bullets only.",
        user="\n\n".join(f"## {c}\n{g}" for c, g in guides.items()),
        model=settings.model_draft,
        max_tokens=1200,
    )
    _save("global", merged.strip(), [])
    return "Built global voice profile."


def get_profile(channel: str) -> tuple[str, list[str]]:
    """(guide, examples) for a channel, falling back to global then empty."""
    with session_scope() as s:
        for key in (channel, "global"):
            row = s.query(StyleProfile).filter_by(channel=key).one_or_none()
            if row:
                return row.guide, list(row.examples or [])
    return "", []
