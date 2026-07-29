"""Stash — the things you forward yourself.

You see a tool on Instagram, a hook on TikTok, a thread on X. You share it to
your own Telegram Saved Messages and forget it. Donna picks it up, works out
what it is, and files it into a bucket:

    tool   something to go and try    -> becomes a to-do on your Today screen
    inspo  creative worth stealing    -> a browsable library, no task pressure
    idea   a business thought         -> same
    read   long stuff for later       -> same

Inside a bucket, items sit in a topic folder ("Claude Code"). Once 3+ items in
one topic share a distinct angle, Donna *proposes* a sub-folder ("Claude Code
for Meta") and waits for your yes — she never silently invents near-duplicates.

When she can't tell what something is — which is most bare Instagram and
Facebook permalinks, since they carry no readable content — she doesn't guess.
She asks you one short question, right back in Saved Messages. Your next plain
message answers it.

Entry points:
  capture_telegram(msg)   a Saved Message arrived
  capture_text(text)      pasted into the dashboard
  answer(item_id, note)   your one-liner, when she asked
  mark_tried(id, verdict) "good, using it" / "meh" -> archived but searchable
  sweep_splits()          hourly: look for sub-folders worth proposing
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Optional

from ..db import (
    ActionLog,
    Bucket,
    BucketProposal,
    Source,
    StashItem,
    StashKind,
    StashStatus,
    Task,
    session_scope,
    utcnow,
)
from .. import brain

# Below this, Donna asks rather than guesses. Tuned for the Instagram problem:
# a bare permalink gives the model nothing, so it should land here, not in a
# plausible-looking wrong folder.
CONFIDENCE_FLOOR = 0.55

# A topic needs this many items before a sub-folder is worth proposing.
SPLIT_MIN_ITEMS = 3

KIND_LABEL = {
    StashKind.tool: "Tools to try",
    StashKind.inspo: "Inspo",
    StashKind.idea: "Ideas",
    StashKind.read: "Read later",
    StashKind.unsorted: "Unsorted",
}

_URL_RE = re.compile(r"https?://[^\s<>\"')]+")

_PLATFORM_HOSTS = [
    ("instagram.com", "instagram"),
    ("facebook.com", "facebook"),
    ("fb.watch", "facebook"),
    ("tiktok.com", "tiktok"),
    ("youtube.com", "youtube"),
    ("youtu.be", "youtube"),
    ("linkedin.com", "linkedin"),
    ("threads.net", "threads"),
    ("reddit.com", "reddit"),
    ("x.com", "x"),
    ("twitter.com", "x"),
]


def _first_url(text: str) -> Optional[str]:
    m = _URL_RE.search(text or "")
    return m.group(0).rstrip(".,)") if m else None


def _platform(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    for needle, name in _PLATFORM_HOSTS:
        if needle in host:
            return name
    return "web"


# ── Buckets ──────────────────────────────────────────────────────────
def _bucket_listing(s) -> str:
    """The topics Donna already has, grouped by kind, for the classifier prompt."""
    lines: list[str] = []
    for kind in (StashKind.tool, StashKind.inspo, StashKind.idea, StashKind.read):
        tops = (
            s.query(Bucket)
            .filter(Bucket.kind == kind, Bucket.parent_id.is_(None))
            .order_by(Bucket.name)
            .all()
        )
        names = []
        for b in tops:
            subs = [c.name for c in s.query(Bucket).filter(Bucket.parent_id == b.id).all()]
            names.append(f"{b.name}" + (f" (sub: {', '.join(subs)})" if subs else ""))
        lines.append(f"  {kind.value}: " + (", ".join(names) if names else "—"))
    return "\n".join(lines)


def _find_or_create_bucket(s, kind: StashKind, name: str, created_by: str = "donna") -> Bucket:
    """Topics are matched case-insensitively so 'claude code' never becomes a
    second 'Claude Code'."""
    name = (name or "General").strip()[:160]
    existing = (
        s.query(Bucket)
        .filter(Bucket.kind == kind, Bucket.parent_id.is_(None))
        .all()
    )
    for b in existing:
        if b.name.lower() == name.lower():
            return b
    b = Bucket(kind=kind, name=name, created_by=created_by)
    s.add(b)
    s.flush()
    return b


# ── Capture ──────────────────────────────────────────────────────────
def _payload(text: str, url: Optional[str], preview: Optional[dict],
             note: Optional[str] = None) -> str:
    parts = []
    if url:
        parts.append(f"LINK: {url}")
    if preview:
        if preview.get("title"):
            parts.append(f"LINK PREVIEW TITLE: {preview['title']}")
        if preview.get("description"):
            parts.append(f"LINK PREVIEW TEXT: {preview['description'][:800]}")
    if preview and preview.get("from"):
        parts.append(f"FORWARDED FROM: {preview['from']}")
    stripped = _URL_RE.sub("", text or "").strip()
    parts.append(f"WHAT THEY SENT: {stripped or '(nothing but the link)'}")
    if note:
        parts.append(f"OWNER'S OWN NOTE (authoritative): {note}")
    return "\n".join(parts)


def _file_item(s, item: StashItem, data: dict, forced_note: Optional[str] = None) -> str:
    """Apply a classification to an item. Returns the line Donna says back."""
    kind_raw = str(data.get("kind", "unsorted"))
    kind = StashKind(kind_raw) if kind_raw in StashKind.__members__ else StashKind.unsorted
    confidence = float(data.get("confidence") or 0)

    item.platform = item.platform or data.get("platform")
    item.title = (data.get("title") or item.title or "Saved post")[:300]
    item.summary = data.get("summary")
    item.why = data.get("why") or None
    item.confidence = confidence

    # Not sure enough to file it, and she wasn't handed a note — so she asks.
    if forced_note is None and (kind == StashKind.unsorted or confidence < CONFIDENCE_FLOOR):
        item.kind = StashKind.unsorted
        item.status = StashStatus.asking
        item.question = (data.get("question")
                         or "What is this one — a tool to try, inspo, an idea, or a read?")[:300]
        return f"Saved, but I can't tell what it is. {item.question}"

    bucket = _find_or_create_bucket(s, kind, data.get("topic") or "General")
    item.kind = kind
    item.bucket_id = bucket.id
    item.status = StashStatus.filed
    item.question = None

    # Only tools earn a to-do — everything else is a library, not a guilt list.
    said_extra = ""
    if kind == StashKind.tool and not item.task_id:
        todo = (data.get("todo") or f"Try {item.title}")[:500]
        task = Task(text=todo, created_by="donna")
        s.add(task)
        s.flush()
        item.task_id = task.id
        said_extra = f"\nTo-do added: {todo}"

    return f"Filed under {KIND_LABEL[kind]} › {bucket.name}.{said_extra}"


def _capture(source: Source, external_id: str, text: str,
             url: Optional[str] = None, preview: Optional[dict] = None) -> dict:
    with session_scope() as s:
        dupe = (
            s.query(StashItem)
            .filter(StashItem.source == source, StashItem.external_id == external_id)
            .first()
        )
        if dupe:
            return {"skipped": "seen", "reply": None}

        url = url or _first_url(text)
        if url:
            already = s.query(StashItem).filter(StashItem.url == url).first()
            if already:
                return {"skipped": "duplicate-url",
                        "reply": f"You already saved that one — it's in {_where(s, already)}."}

        item = StashItem(
            source=source, external_id=external_id, url=url,
            platform=_platform(url), raw_text=(text or "")[:4000],
            status=StashStatus.filed,
        )
        s.add(item)
        s.flush()

        try:
            data = brain.classify_stash(_payload(text, url, preview), _bucket_listing(s))
        except Exception:
            # The brain is down or gave us nothing usable — keep the item, ask later.
            item.kind = StashKind.unsorted
            item.status = StashStatus.asking
            item.title = (url or (text or "Saved post"))[:300]
            item.question = "I couldn't read this one — what is it?"
            return {"item_id": item.id, "asking": True,
                    "reply": "Saved it, but I couldn't read it. What is it?"}

        reply = _file_item(s, item, data)
        s.add(ActionLog(
            summary=(f"Stashed “{item.title}” — waiting on you to say what it is"
                     if item.status == StashStatus.asking
                     else f"Stashed “{item.title}” → {_where(s, item)}"),
            source=source,
        ))
        return {
            "item_id": item.id,
            "asking": item.status == StashStatus.asking,
            "kind": item.kind.value,
            "reply": reply,
        }


def _where(s, item: StashItem) -> str:
    b = s.get(Bucket, item.bucket_id) if item.bucket_id else None
    if not b:
        return "your stash"
    parent = s.get(Bucket, b.parent_id) if b.parent_id else None
    path = f"{parent.name} › {b.name}" if parent else b.name
    return f"{KIND_LABEL.get(item.kind, 'Stash')} › {path}"


def capture_text(text: str, source: Source = Source.web) -> dict:
    """Pasted into the dashboard. The external id is a stable digest of the
    content, so re-pasting the same thing is a no-op across restarts too."""
    key = (_first_url(text) or (text or "").strip())[:400]
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return _capture(source, f"paste:{digest}", text)


def capture_telegram(msg) -> dict:
    """A message dropped in Saved Messages.

    A plain message with no link, arriving while Donna has an open question, is
    read as the *answer* to that question rather than as a new item — which is
    what makes "forward, get asked, reply" work as one continuous exchange.
    """
    text = msg.text or ""
    if not _first_url(text) and not msg.url:
        pending = _oldest_open_question()
        if pending:
            return answer(pending, text)
        if not text.strip():
            return {"skipped": "empty", "reply": None}

    preview = {"title": msg.preview_title, "description": msg.preview_desc,
               "from": msg.forwarded_from}
    return _capture(Source.telegram, f"saved:{msg.id}", text, url=msg.url, preview=preview)


def _oldest_open_question(within_hours: int = 24) -> Optional[int]:
    with session_scope() as s:
        cutoff = utcnow() - dt.timedelta(hours=within_hours)
        row = (
            s.query(StashItem)
            .filter(StashItem.status == StashStatus.asking, StashItem.created_at >= cutoff)
            .order_by(StashItem.created_at.desc())
            .first()
        )
        return row.id if row else None


# ── Your answers ─────────────────────────────────────────────────────
def answer(item_id: int, note: str) -> dict:
    """Your one line about an item Donna couldn't place. Re-runs the classifier
    with your note as the authority, so it can no longer come back unsorted."""
    with session_scope() as s:
        item = s.get(StashItem, item_id)
        if not item:
            return {"error": "not found", "reply": None}
        item.note = (note or "")[:500]
        try:
            data = brain.classify_stash(
                _payload(item.raw_text or "", item.url, None, note=item.note),
                _bucket_listing(s),
            )
        except Exception:
            return {"item_id": item.id, "reply": "Still couldn't reach my brain — try again in a bit."}
        reply = _file_item(s, item, data, forced_note=item.note)
        return {"item_id": item.id, "kind": item.kind.value, "reply": reply}


def set_kind(item_id: int, kind: str, topic: Optional[str] = None) -> dict:
    """Manual override — you pick the bucket yourself.

    With no topic given this lands in "General" on purpose: naming the folder
    after the item would mint a one-item folder per capture, which is the
    near-duplicate mess the split-on-3 rule exists to avoid.
    """
    with session_scope() as s:
        item = s.get(StashItem, item_id)
        if not item or kind not in StashKind.__members__:
            return {"error": "bad request"}
        k = StashKind(kind)
        bucket = _find_or_create_bucket(
            s, k, (topic or "").strip() or "General", created_by="you"
        )
        item.kind = k
        item.bucket_id = bucket.id
        item.status = StashStatus.filed
        item.question = None
        if k == StashKind.tool and not item.task_id:
            task = Task(text=f"Try {item.title}"[:500], created_by="donna")
            s.add(task)
            s.flush()
            item.task_id = task.id
        return {"ok": True, "where": _where(s, item)}


def move(item_id: int, bucket_id: int) -> dict:
    with session_scope() as s:
        item, bucket = s.get(StashItem, item_id), s.get(Bucket, bucket_id)
        if not item or not bucket:
            return {"error": "not found"}
        item.bucket_id = bucket.id
        item.kind = bucket.kind
        item.status = StashStatus.filed
        return {"ok": True, "where": _where(s, item)}


def mark_tried(item_id: int, verdict: str) -> dict:
    """You tried it. The verdict is the whole point — it's why you never
    re-evaluate the same tool twice."""
    with session_scope() as s:
        item = s.get(StashItem, item_id)
        if not item:
            return {"error": "not found"}
        item.verdict = (verdict or "")[:500]
        item.status = StashStatus.tried
        item.decided_at = utcnow()
        if item.task_id:
            task = s.get(Task, item.task_id)
            if task:
                task.done = True
        s.add(ActionLog(summary=f"Tried {item.title} — {item.verdict}", source=Source.system))
        return {"ok": True}


def archive(item_id: int) -> dict:
    with session_scope() as s:
        item = s.get(StashItem, item_id)
        if item:
            item.status = StashStatus.archived
            item.decided_at = utcnow()
            if item.task_id:
                task = s.get(Task, item.task_id)
                if task:
                    task.done = True
        return {"ok": True}


# ── Splitting topics into sub-folders ────────────────────────────────
def sweep_splits() -> dict:
    """Look at every topic with enough items and ask whether it wants splitting.

    Runs on the hourly loop rather than on capture, so forwarding stays instant.
    Only proposes — nothing moves until you accept.
    """
    proposed = 0
    with session_scope() as s:
        topics = s.query(Bucket).filter(Bucket.parent_id.is_(None)).all()
        for b in topics:
            items = (
                s.query(StashItem)
                .filter(StashItem.bucket_id == b.id,
                        StashItem.status == StashStatus.filed)
                .all()
            )
            if len(items) < SPLIT_MIN_ITEMS:
                continue
            open_already = (
                s.query(BucketProposal)
                .filter(BucketProposal.bucket_id == b.id, BucketProposal.status == "pending")
                .count()
            )
            if open_already:
                continue

            existing_subs = {
                c.name.lower() for c in s.query(Bucket).filter(Bucket.parent_id == b.id).all()
            }
            corpus = "\n".join(
                f"{it.id}. {it.title} — {it.summary or ''} {it.note or ''}".strip()
                for it in items
            )
            try:
                suggestions = brain.propose_splits(b.name, corpus)
            except Exception:
                continue

            valid_ids = {it.id for it in items}
            for sug in suggestions:
                members = [i for i in sug.get("member_ids", []) if i in valid_ids]
                name = (sug.get("name") or "").strip()
                # Guard the model's two failure modes: too-small groups, and a
                # sub-folder that would just swallow the whole topic.
                if (len(members) < SPLIT_MIN_ITEMS or not name
                        or len(members) >= len(items)
                        or name.lower() in existing_subs
                        or name.lower() == b.name.lower()):
                    continue
                s.add(BucketProposal(
                    bucket_id=b.id, name=name[:160],
                    rationale=(sug.get("rationale") or "")[:400],
                    item_ids=members,
                ))
                existing_subs.add(name.lower())
                proposed += 1
    return {"proposed": proposed}


def accept_proposal(proposal_id: int) -> dict:
    with session_scope() as s:
        p = s.get(BucketProposal, proposal_id)
        if not p or p.status != "pending":
            return {"error": "not found"}
        parent = s.get(Bucket, p.bucket_id)
        if not parent:
            return {"error": "not found"}
        child = Bucket(kind=parent.kind, name=p.name, parent_id=parent.id, created_by="donna")
        s.add(child)
        s.flush()
        moved = 0
        for iid in p.item_ids or []:
            item = s.get(StashItem, iid)
            if item and item.bucket_id == parent.id:
                item.bucket_id = child.id
                moved += 1
        p.status = "accepted"
        s.add(ActionLog(
            summary=f"Split “{parent.name}” → “{child.name}” ({moved} items)",
            source=Source.system,
        ))
        return {"ok": True, "moved": moved}


def reject_proposal(proposal_id: int) -> dict:
    with session_scope() as s:
        p = s.get(BucketProposal, proposal_id)
        if p:
            p.status = "rejected"
        return {"ok": True}


def rename_bucket(bucket_id: int, name: str) -> dict:
    with session_scope() as s:
        b = s.get(Bucket, bucket_id)
        if not b or not (name or "").strip():
            return {"error": "bad request"}
        b.name = name.strip()[:160]
        return {"ok": True}
