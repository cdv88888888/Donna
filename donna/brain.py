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


def summarize_action(draft_body: str) -> str:
    """Compress a draft into one plain line: 'Donna will …' (no 'Donna will' prefix)."""
    line = _call(
        settings.model_triage,
        system="Summarize what this reply does in ONE short line (max 14 words), "
        "starting with a verb (e.g. 'Confirm the terms and ask for the signed PDF'). "
        "No quotes, no preamble.",
        user=draft_body,
        max_tokens=60,
    )
    return line.strip().strip('"')


CLUSTER_SYSTEM = """You are {owner}'s chief of staff. Below are recent messages \
and events from their Gmail, Telegram, and Calendar. Group the ones that belong \
to the same real project/initiative (a deal, a client matter, a deliverable, \
anything with an outcome, deadline, or money). Ignore one-off noise \
(newsletters, receipts, automated notices) — those are not projects.

A cluster only counts as a project if it has 2+ related messages OR a clear \
client/company, deadline, or money attached.

Return ONLY a JSON array. Each element:
{{"name":"short project name (include company if relevant)","company":"or null",
"next_action":"the single next thing to do, in one line","owes":"who owes what, or null",
"amount":"e.g. ₱2.4M / overdue 12d / null","deadline":"YYYY-MM-DD or null",
"participants":["display names"],"match_keys":["emails, invoice#s, distinctive keywords"],
"member_ids":[the id numbers of the messages in this cluster]}}"""


def cluster_projects(corpus: str) -> list[dict]:
    """Group message summaries into projects. `corpus` lists items prefixed by id."""
    raw = _call(
        settings.model_draft,
        CLUSTER_SYSTEM.format(owner=settings.owner_name),
        corpus,
        max_tokens=2500,
    )
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        return []
    return json.loads(raw[start : end + 1])


STASH_SYSTEM = """You are Donna, {owner}'s chief of staff. They just forwarded \
you something they saw on social media. File it.

There are exactly four buckets. Pick one:
  tool  — a product, app, model, framework, or platform they could go and *try*.
          This is the only kind that becomes a to-do.
  inspo — content and creative worth stealing from: hooks, formats, edits, ad angles.
  idea  — a business thought worth chewing on (ops, marketing, a competitor move).
  read  — a long post, thread, or video worth their time later. Nothing to try.

Inside a bucket, items live in a topic folder — "Claude Code", "Short-form Hooks",
"LPG Pricing". Reuse an existing topic whenever the item plausibly belongs there;
invent a new one only when nothing fits. Topic names are short title-case noun
phrases, no punctuation.

EXISTING TOPICS (reuse these before inventing):
{buckets}

Be honest when you don't know. Instagram and Facebook links carry almost no
readable content — if all you have is a bare permalink with no caption, you
genuinely cannot tell what it is, and guessing is worse than asking. Then: set
kind to "unsorted", confidence to 0, and write the one short question you'd ask
{owner} to place it. Never invent a product name you cannot see in the text.

If {owner} has given you their own note about the item, trust it completely —
it outranks anything you infer, and you must NOT return "unsorted".

Return ONLY a JSON object:
{{"platform":"instagram|facebook|x|youtube|tiktok|linkedin|threads|reddit|web",
"title":"<=70 chars — what this actually is",
"kind":"tool|inspo|idea|read|unsorted",
"topic":"topic folder name, or null when unsorted",
"topic_is_new":true|false,
"confidence":0.0-1.0,
"summary":"one line: what it is",
"why":"one line: why they kept it, or null",
"todo":"only when kind is tool — an action starting with a verb, e.g. \
'Try Cursor Composer on the ERP repo'. Otherwise null",
"question":"only when unsorted — one short question. Otherwise null"}}"""


def classify_stash(payload: str, bucket_listing: str) -> dict:
    """Decide which bucket and topic a forwarded post belongs in."""
    system = STASH_SYSTEM.format(
        owner=settings.owner_name,
        buckets=bucket_listing or "(none yet — this is the first thing they've saved)",
    )
    raw = _call(settings.model_triage, system, payload[:6000], max_tokens=500)
    return _extract_json(raw)


SPLIT_SYSTEM = """You are tidying {owner}'s "{bucket}" folder. Its items are \
listed below. If 3 OR MORE of them share a distinct, nameable angle, propose \
splitting that group into a sub-folder — e.g. a "Claude Code" folder where \
several items are specifically about running it against Meta ad accounts earns \
a "Claude Code for Meta" sub-folder.

Be conservative. Most folders have no real sub-structure and should return [].
Never propose a sub-folder for fewer than 3 items, never propose one that would
swallow the whole folder, and never propose two that mean the same thing.

Return ONLY a JSON array (empty if nothing is worth splitting):
[{{"name":"sub-folder name, short and specific","rationale":"one line: why these \
belong together","member_ids":[the id numbers]}}]"""


def propose_splits(bucket_name: str, corpus: str) -> list[dict]:
    """Suggest sub-folders for one topic. `corpus` lists items prefixed by id."""
    raw = _call(
        settings.model_draft,
        SPLIT_SYSTEM.format(owner=settings.owner_name, bucket=bucket_name),
        corpus[:12000],
        max_tokens=1200,
    ).strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        return []
    return json.loads(raw[start : end + 1])


def ask(system: str, user: str, model: Optional[str] = None, max_tokens: int = 1500) -> str:
    """General-purpose call for the command bar and the daily brief."""
    return _call(model or settings.model_draft, system, user, max_tokens=max_tokens)
