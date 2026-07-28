#!/usr/bin/env python3
"""Generate a Telegram session string for Donna's userbot.

Run this ONCE, locally, on a machine where you can receive your Telegram login
code. It logs in as you and prints a StringSession. Paste that value into the
TELEGRAM_SESSION deployment secret.

    python scripts/setup_telegram.py

Requires TELEGRAM_API_ID and TELEGRAM_API_HASH in your environment / .env
(get them from https://my.telegram.org -> API development tools).

SECURITY: this string can act as your Telegram account. Never commit it, never
share it, and store it only as a secret.
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()

try:
    from telethon.sync import TelegramClient
    from telethon.sessions import StringSession
except ImportError:
    sys.exit("Telethon not installed. Run: pip install -r requirements.txt")

api_id = os.environ.get("TELEGRAM_API_ID")
api_hash = os.environ.get("TELEGRAM_API_HASH")
if not (api_id and api_hash):
    sys.exit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH first (see .env.example).")

print("Logging in to Telegram — you'll be asked for your phone and login code.\n")
with TelegramClient(StringSession(), int(api_id), api_hash) as client:
    session = client.session.save()
    me = client.get_me()
    print(f"\n✓ Logged in as {me.first_name} (@{me.username}).")
    print("\nAdd this to your secrets as TELEGRAM_SESSION (keep it private):\n")
    print(session)
    print("\nAlso set OWNER_TELEGRAM_ID =", me.id)
