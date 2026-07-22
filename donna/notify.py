"""Web push — sends phone notifications to the installed PWA.

Uses VAPID keys (generated once by scripts/setup_google.py's sibling or on first
boot) stored in settings/secrets. Silently no-ops if push isn't configured yet,
so the rest of Donna keeps working before you set up notifications.
"""
from __future__ import annotations

import json
import os

from .db import PushSub, session_scope

VAPID_PRIVATE = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:donna@localhost")


def _send(sub: PushSub, payload: dict) -> bool:
    try:
        from pywebpush import webpush  # imported lazily so absence isn't fatal

        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE,
            vapid_claims={"sub": VAPID_SUBJECT},
        )
        return True
    except Exception:
        return False


def push(title: str, body: str, url: str = "/") -> int:
    """Send a notification to every registered device. Returns count delivered."""
    if not (VAPID_PRIVATE and VAPID_PUBLIC):
        return 0
    delivered = 0
    with session_scope() as s:
        subs = s.query(PushSub).all()
        for sub in subs:
            if _send(sub, {"title": title, "body": body, "url": url}):
                delivered += 1
            else:
                s.delete(sub)  # drop dead endpoints
    return delivered


def push_if_urgent(title: str, reason: str) -> None:
    push(f"⚡ {title}", reason or "Needs your attention", url="/")
