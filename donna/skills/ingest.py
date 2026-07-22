"""Ingest pipeline — the heart of Donna's triage.

For each new message (email or Telegram DM):
  1. Resolve the sender to a contact (VIP?).
  2. Ask the brain to triage it.
  3. If it needs you  -> create an Item, and if a reply is warranted, a Draft in
     your voice awaiting approval; ping your phone if urgent.
  4. If it's noise    -> auto-handle (archive mail) and log it under "Handled".

Nothing is ever sent automatically here — drafts wait for approval. The only
autonomous actions are archiving low-value mail and logging.
"""
from __future__ import annotations

from ..config import settings
from ..db import (
    Draft,
    Item,
    ItemStatus,
    Priority,
    Source,
    ActionLog,
    session_scope,
)
from .. import brain, voice
from . import contacts

_PRIORITY = {p.value: p for p in Priority}


def _already_seen(s, source: Source, external_id: str) -> bool:
    return (
        s.query(Item)
        .filter(Item.source == source, Item.external_id == external_id)
        .first()
        is not None
    )


def process_email(mail) -> dict:
    """Triage one Gmail message. Returns a small dict describing what happened."""
    from ..integrations import gmail

    with session_scope() as s:
        if _already_seen(s, Source.gmail, mail.id):
            return {"skipped": "seen"}

        contact = contacts.upsert_email(s, mail.sender_email, mail.sender)
        t = brain.triage(mail.sender, mail.subject, mail.body, is_vip=contact.is_vip)

        # VIPs always surface, regardless of the model's call.
        needs_you = t.needs_you or contact.is_vip

        if not needs_you:
            gmail.archive(mail.id)
            s.add(ActionLog(
                summary=f"Archived: {mail.subject or '(no subject)'} — {t.category}",
                source=Source.gmail,
            ))
            return {"handled": True, "category": t.category}

        item = Item(
            source=Source.gmail,
            external_id=mail.id,
            thread_id=mail.thread_id,
            sender=mail.sender,
            sender_contact_id=contact.id,
            subject=mail.subject,
            snippet=mail.snippet,
            body=mail.body[:8000],
            priority=_PRIORITY.get(t.priority, Priority.normal),
            reason=t.reason,
            status=ItemStatus.open,
        )
        s.add(item)
        s.flush()

        made_draft = False
        if t.suggested_action == "draft_reply":
            guide, examples = voice.get_profile("email")
            body = brain.draft(
                channel="email",
                incoming=f"From {mail.sender}\nSubject: {mail.subject}\n\n{mail.body}",
                style_guide=guide,
                examples=examples,
            )
            s.add(Draft(
                item_id=item.id, channel=Source.gmail,
                to=mail.sender_email, body=body,
            ))
            made_draft = True

        return {
            "needs_you": True,
            "priority": t.priority,
            "draft": made_draft,
            "reason": t.reason,
            "item_id": item.id,
        }


def process_telegram(msg) -> dict:
    """Triage one incoming Telegram DM."""
    with session_scope() as s:
        ext = f"{msg.chat_id}:{msg.id}"
        if _already_seen(s, Source.telegram, ext):
            return {"skipped": "seen"}

        contact = contacts.upsert_telegram(s, msg.sender_id, msg.sender_name)
        t = brain.triage(msg.sender_name, "(telegram)", msg.text, is_vip=contact.is_vip)
        needs_you = t.needs_you or contact.is_vip

        if not needs_you:
            s.add(ActionLog(
                summary=f"Telegram from {msg.sender_name}: no action needed",
                source=Source.telegram,
            ))
            return {"handled": True}

        item = Item(
            source=Source.telegram,
            external_id=ext,
            thread_id=str(msg.chat_id),
            sender=msg.sender_name,
            sender_contact_id=contact.id,
            subject=msg.text[:80],
            snippet=msg.text[:280],
            body=msg.text[:8000],
            priority=_PRIORITY.get(t.priority, Priority.normal),
            reason=t.reason,
            status=ItemStatus.open,
        )
        s.add(item)
        s.flush()

        made_draft = False
        if t.suggested_action == "draft_reply":
            guide, examples = voice.get_profile("telegram")
            body = brain.draft(
                channel="telegram",
                incoming=f"{msg.sender_name}: {msg.text}",
                style_guide=guide,
                examples=examples,
            )
            s.add(Draft(item_id=item.id, channel=Source.telegram,
                        to=str(msg.chat_id), body=body))
            made_draft = True

        return {"needs_you": True, "priority": t.priority,
                "draft": made_draft, "item_id": item.id}


def poll_inbox() -> dict:
    """Scheduled sweep: triage all unread mail. Returns a run summary."""
    from ..integrations import gmail
    from ..notify import push_if_urgent

    seen = handled = surfaced = 0
    for mail in gmail.fetch_unread():
        result = process_email(mail)
        if result.get("skipped"):
            continue
        seen += 1
        if result.get("handled"):
            handled += 1
        elif result.get("needs_you"):
            surfaced += 1
            gmail.mark_read(mail.id)
            if result.get("priority") in ("urgent", "high"):
                push_if_urgent(mail.subject or "New message", result.get("reason", ""))
    return {"seen": seen, "handled": handled, "surfaced": surfaced}
