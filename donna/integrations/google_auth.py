"""Shared Google OAuth credential loading for Gmail + Calendar.

Credentials come from GOOGLE_TOKEN_JSON (a single-line JSON blob you paste
into deployment secrets, produced by scripts/setup_google.py). Falling back
to a token file is supported for local runs.
"""
from __future__ import annotations

import json
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from ..config import settings

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]

_TOKEN_FILE = "token_google.json"


def load_credentials() -> Credentials:
    """Return valid, refreshed Google credentials or raise a clear error."""
    info = None
    if settings.google_token_json:
        info = json.loads(settings.google_token_json)
    elif os.path.exists(_TOKEN_FILE):
        with open(_TOKEN_FILE) as f:
            info = json.load(f)

    if not info:
        raise RuntimeError(
            "No Google token. Run `python scripts/setup_google.py` and set "
            "GOOGLE_TOKEN_JSON (or provide token_google.json)."
        )

    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds
