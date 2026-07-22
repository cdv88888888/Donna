"""Contact lookup — resolves senders to known people and flags VIPs."""
from __future__ import annotations

from typing import Optional

from ..db import Contact


def find_by_email(s, email: str) -> Optional[Contact]:
    if not email:
        return None
    return s.query(Contact).filter(Contact.email == email.lower()).one_or_none()


def find_by_telegram(s, telegram_id: int) -> Optional[Contact]:
    return s.query(Contact).filter(Contact.telegram_id == telegram_id).one_or_none()


def upsert_email(s, email: str, name: str) -> Contact:
    c = find_by_email(s, email)
    if not c:
        c = Contact(name=name or email, email=email.lower())
        s.add(c)
        s.flush()
    return c


def upsert_telegram(s, telegram_id: int, name: str) -> Contact:
    c = find_by_telegram(s, telegram_id)
    if not c:
        c = Contact(name=name, telegram_id=telegram_id)
        s.add(c)
        s.flush()
    return c
