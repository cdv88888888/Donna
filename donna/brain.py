"""The brain — a thin wrapper over Claude for the two jobs Donna does most:

  triage()  -> fast, cheap classification of an incoming message
  draft()   -> a reply written in the owner's trained voice

Model choice is deliberate: a small/fast model for triage (runs on every
message), a strong model for drafting (quality matters, runs rarely).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import settings

_client = Anthropic(api_key=settings.anthropic_api_key)


@dataclass
class Triage:
    priority: str          # urgent | high | normal | low
    needs_you: bool        # should this surface in "Needs you"?
    reason: str            # one line: why
    category: str          # reply_needed | fyi | scheduling | newsletter | receipt | spam
    suggested_action: str  # draft_reply | schedule | archive | none


def _extract_json(text: str) -> dict:
    """Claude sometimes wraps JSON in prose or fences; pull the object out."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1].lstrip("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        return json.loads(text[start : end + 1])
    raise ValueError(f"No JSON object in model output: {text[:200]}")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def _call(model: str, system: str, user: str, max_tokens: int = 1024) -> str:
    resp = _client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in resp.content if block.type == "text")


TRIAGE_SYSTEM = """You are Donna, {owner}'s executive assistant. Your job is \
to protect their attention. You are triaging one incoming message. Decide how \
much it needs {owner} personally.

Be ruthless about what counts as "needs you". These DO: a real person asking a \
question, a decision only {owner} can make, anything time-sensitive, money, \
legal, or from a VIP. These do NOT: newsletters, receipts, automated notices, \
marketing, FYIs with no action, things you can safely handle yourself.

Respond with ONLY a JSON object:
{{"priority":"urgent|high|normal|low","needs_you":true|false,\
"category":"reply_needed|fyi|scheduling|newsletter|receipt|spam|other",\
"suggested_action":"draft_reply|schedule|archive|none","reason":"<=12 words"}}"""


def triage(sender: str, subject: str, body: str, is_vip: bool = False) -> Triage:
    system = TRIAGE_SYSTEM.format(owner=settings.owner_name)
    vip = "\n\nNOTE: This sender is a VIP — err toward surfacing it." if is_vip else ""
    user = f"From: {sender}\nSubject: {subject}\n\n{body[:4000]}{vip}"
    raw = _call(settings.model_triage, system, user, max_tokens=300)
    data = _extract_json(raw)
    return Triage(
        priority=data.get("priority", "normal"),
        needs_you=bool(data.get("needs_you", True)),
        reason=data.get("reason", ""),
        category=data.get("category", "other"),
        suggested_action=data.get("suggested_action", "none"),
    )


DRAFT_SYSTEM = """You are Donna, writing a reply AS {owner} — in their own \
voice, not yours. The reply must be indistinguishable from something {owner} \
wrote themselves.

Study this voice profile carefully and imitate it — tone, length, greetings, \
sign-off, punctuation, emoji habits, and any language mixing:
────────────────────────────────────────
{style_guide}
────────────────────────────────────────
{examples}

Rules:
- Match the channel ({channel}). Email can be a touch more complete; chat is short.
- Never invent facts, commitments, dates, numbers, or names {owner} didn't give you.
- If you're missing information needed to reply, write the best version you can \
and note what's uncertain in a trailing line prefixed with "⚠ ".
- Output ONLY the message body. No preamble, no "Here's a draft", no subject line."""


def draft(
    channel: str,
    incoming: str,
    style_guide: str,
    examples: Optional[list[str]] = None,
    context: str = "",
    instruction: str = "",
) -> str:
    ex = ""
    if examples:
        joined = "\n\n".join(f"— {e}" for e in examples[:6])
        ex = f"Here are real examples of how {settings.owner_name} writes:\n{joined}"
    system = DRAFT_SYSTEM.format(
        owner=settings.owner_name,
        style_guide=style_guide or "(no profile yet — write clear, warm, concise)",
        examples=ex,
        channel=channel,
    )
    parts = [f"Message to reply to:\n{incoming}"]
    if context:
        parts.append(f"\nRelevant context:\n{context}")
    if instruction:
        parts.append(f"\n{settings.owner_name}'s instruction for this reply: {instruction}")
    body = _call(settings.model_draft, system, "\n".join(parts), max_tokens=1200)
    return body.strip()


def ask(system: str, user: str, model: Optional[str] = None, max_tokens: int = 1500) -> str:
    """General-purpose call for the command bar and the daily brief."""
    return _call(model or settings.model_draft, system, user, max_tokens=max_tokens)
