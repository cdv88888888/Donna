"""Gmail integration — read new mail, extract clean text, draft, send, label.

Donna reads mail to triage it, creates Gmail drafts for replies she proposes,
and sends only after you approve. She never deletes; low-value mail is archived
(remove INBOX label) so your inbox stays quiet without losing anything.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from email.mime.text import MIMEText
from typing import Optional

from googleapiclient.discovery import build

from .google_auth import load_credentials


@dataclass
class Mail:
    id: str
    thread_id: str
    sender: str          # "Name <email>"
    sender_email: str
    subject: str
    snippet: str
    body: str
    date: str


def _service():
    return build("gmail", "v1", credentials=load_credentials(), cache_discovery=False)


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _decode_body(payload: dict) -> str:
    """Walk the MIME tree and return the best plain-text body we can find."""
    def walk(part) -> Optional[str]:
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if mime == "text/plain" and data:
            return base64.urlsafe_b64decode(data).decode("utf-8", "replace")
        for sub in part.get("parts", []) or []:
            found = walk(sub)
            if found:
                return found
        if mime == "text/html" and data:
            html = base64.urlsafe_b64decode(data).decode("utf-8", "replace")
            return re.sub(r"<[^>]+>", " ", html)
        return None

    text = walk(payload) or ""
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _parse_email(addr: str) -> str:
    m = re.search(r"<([^>]+)>", addr)
    return (m.group(1) if m else addr).strip().lower()


def fetch_unread(max_results: int = 25) -> list[Mail]:
    """Unread messages in the inbox, newest first."""
    svc = _service()
    resp = (
        svc.users().messages()
        .list(userId="me", q="is:unread in:inbox", maxResults=max_results)
        .execute()
    )
    out: list[Mail] = []
    for ref in resp.get("messages", []):
        msg = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        headers = msg["payload"].get("headers", [])
        sender = _header(headers, "From")
        out.append(
            Mail(
                id=msg["id"],
                thread_id=msg["threadId"],
                sender=sender,
                sender_email=_parse_email(sender),
                subject=_header(headers, "Subject"),
                snippet=msg.get("snippet", ""),
                body=_decode_body(msg["payload"]),
                date=_header(headers, "Date"),
            )
        )
    return out


def create_draft(thread_id: str, to: str, subject: str, body: str) -> str:
    svc = _service()
    mime = MIMEText(body)
    mime["To"] = to
    mime["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    draft = (
        svc.users().drafts()
        .create(userId="me", body={"message": {"raw": raw, "threadId": thread_id}})
        .execute()
    )
    return draft["id"]


def send_draft(draft_id: str) -> str:
    svc = _service()
    sent = svc.users().drafts().send(userId="me", body={"id": draft_id}).execute()
    return sent["id"]


def send_reply(thread_id: str, to: str, subject: str, body: str) -> str:
    """Create and immediately send (used once you've approved)."""
    return send_draft(create_draft(thread_id, to, subject, body))


def archive(message_id: str) -> None:
    """Remove from inbox without deleting — Donna's 'handled' move."""
    _service().users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["INBOX", "UNREAD"]}
    ).execute()


def mark_read(message_id: str) -> None:
    _service().users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()


def list_sent(max_results: int = 200) -> list[Mail]:
    """Recent sent mail — the training data for Donna's email voice."""
    svc = _service()
    resp = (
        svc.users().messages()
        .list(userId="me", q="in:sent", maxResults=max_results)
        .execute()
    )
    out: list[Mail] = []
    for ref in resp.get("messages", []):
        msg = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        headers = msg["payload"].get("headers", [])
        out.append(
            Mail(
                id=msg["id"],
                thread_id=msg["threadId"],
                sender=_header(headers, "From"),
                sender_email="",
                subject=_header(headers, "Subject"),
                snippet=msg.get("snippet", ""),
                body=_decode_body(msg["payload"]),
                date=_header(headers, "Date"),
            )
        )
    return out
