#!/usr/bin/env python3
"""Authorize Donna for Gmail + Google Calendar and print a token blob.

Run ONCE locally. It opens a browser for Google consent, then prints a single
line of JSON. Paste that into the GOOGLE_TOKEN_JSON deployment secret.

    python scripts/setup_google.py

Prerequisite: a Google Cloud OAuth *Desktop app* client secret JSON. Steps:
  1. console.cloud.google.com -> create/select a project
  2. Enable the Gmail API and Google Calendar API
  3. APIs & Services -> Credentials -> Create OAuth client ID -> Desktop app
  4. Download the JSON, save it as client_secret.json (or set
     GOOGLE_CLIENT_SECRET_FILE to its path)
  5. Add your email as a test user on the OAuth consent screen
"""
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    sys.exit("Deps missing. Run: pip install -r requirements.txt")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]

secret_file = os.environ.get("GOOGLE_CLIENT_SECRET_FILE", "client_secret.json")
if not os.path.exists(secret_file):
    sys.exit(f"OAuth client secret not found at '{secret_file}'. See the header of this file.")

flow = InstalledAppFlow.from_client_secrets_file(secret_file, SCOPES)
creds = flow.run_local_server(port=0)

blob = json.loads(creds.to_json())
# Persist locally for convenience and print for the secret.
with open("token_google.json", "w") as f:
    json.dump(blob, f)

print("\n✓ Authorized Gmail + Calendar. Saved token_google.json.")
print("\nSet this as GOOGLE_TOKEN_JSON (single line):\n")
print(json.dumps(blob))
