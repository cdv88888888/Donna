# Setting up Donna

This walks you from an empty repo to a running, always-on assistant. Budget
about 30–40 minutes; most of it is clicking through Google and Telegram
consent screens. You only do it once.

Everything secret is pasted into environment variables — never into code or
git. `.env` and all token files are already git-ignored.

---

## 0. Prerequisites

- Python 3.11+
- A Gmail/Google account (the one Donna will manage)
- A Telegram account
- An Anthropic (Claude) API key
- ~US$5/mo for hosting (Railway) — optional; you can run locally first

```bash
git clone <your-repo> && cd Donna
pip install -r requirements.txt
cp .env.example .env
```

Keep `.env` open — you'll fill it in step by step.

---

## 1. The brain — Anthropic API key

1. Go to **console.anthropic.com** → *API Keys* → create a key.
2. Add a little credit (Billing). Triage runs on Sonnet (cheap); drafts on Opus.
   Real-world usage for one person is typically a few dollars a month.
3. In `.env`: `ANTHROPIC_API_KEY=sk-ant-...`

Also set your identity in `.env`: `OWNER_NAME`, `OWNER_EMAIL`, `OWNER_TIMEZONE`
(e.g. `Asia/Manila`).

---

## 2. Gmail + Google Calendar

1. **console.cloud.google.com** → create a project (any name).
2. *APIs & Services → Library* → enable **Gmail API** and **Google Calendar API**.
3. *APIs & Services → OAuth consent screen* → External → add your own email as a
   **Test user** (this keeps it private to you).
4. *Credentials → Create credentials → OAuth client ID → Desktop app* → download
   the JSON, save it as `client_secret.json` in the project root.
5. Authorize:
   ```bash
   python scripts/setup_google.py
   ```
   A browser opens; approve Gmail + Calendar. The script prints a single line of
   JSON and saves `token_google.json`.
6. In `.env`: paste that line as `GOOGLE_TOKEN_JSON=...`

---

## 3. Telegram userbot

This logs Donna in **as you**, so she can learn your voice from your chats and
send on your behalf after approval.

1. **my.telegram.org** → *API development tools* → note your **api_id** and
   **api_hash**.
2. In `.env`: `TELEGRAM_API_ID=...`, `TELEGRAM_API_HASH=...`
3. Log in:
   ```bash
   python scripts/setup_telegram.py
   ```
   Enter your phone and the code Telegram sends you. It prints a
   **session string** and your numeric user id.
4. In `.env`: `TELEGRAM_SESSION=<the string>` and `OWNER_TELEGRAM_ID=<your id>`.

> The session string can act as your Telegram account. Treat it like a password —
> it only ever belongs in the secret, never in git.

The same login is what powers the **Stash**: once she's connected, anything you
drop in your own **Saved Messages** gets filed. Nothing extra to set up — share
a post from Instagram, Facebook, TikTok or X to Telegram → yourself, and Donna
replies in that chat telling you where she put it.

---

## 4. Phone push notifications

```bash
python scripts/setup_push.py
```

Paste the three printed values into `.env`: `VAPID_PUBLIC_KEY`,
`VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`.

---

## 5. Train your voice

```bash
python scripts/train_voice.py
```

Donna reads your recent sent email and Telegram messages, distills a style
guide per channel, and stores it. Re-run this any time to refresh her voice.

---

## 6. Run her

```bash
python -m donna.main
# open http://localhost:8000
```

On your phone, open the URL and **Add to Home Screen** to install the app and
enable push. First inbox sweep runs within `INBOX_POLL_MINUTES`; the morning
brief fires at `BRIEF_TIME`.

Tune behavior in `.env`:

| Setting | Meaning |
|---|---|
| `COMMS_AUTONOMY` | `draft` (approve everything) or `auto_low` (auto-send low-stakes) |
| `CALENDAR_AUTONOMY` | `auto` lets her move meetings without asking |
| `INBOX_POLL_MINUTES` | how often she sweeps the inbox |
| `BRIEF_TIME` | when the morning brief is sent (owner timezone) |
| `NUDGE_AFTER_DAYS` | how stale a thread gets before it's nudge-worthy |

Mark VIPs by setting `is_vip` on their row in the `contacts` table (a small
admin UI for this is a good next addition).

---

## 7. Deploy always-on (Railway)

A proactive assistant must run 24/7. Locally your laptop sleeps — so deploy.

1. Push this repo to GitHub.
2. **railway.app** → *New Project → Deploy from GitHub repo* → pick this repo.
   Railway detects the `Dockerfile`.
3. *Variables* → add **every** key from your `.env` (Railway is where the
   secrets live in production).
4. Add a **Volume** mounted at `/data` so the SQLite database persists across
   deploys. (`DATABASE_URL` already points there in the Dockerfile.)
5. Deploy. Open the generated URL on your phone and install it.

To update her later: push to GitHub; Railway redeploys automatically.

> **Fly.io** works equally well — `fly launch` detects the Dockerfile; set the
> same secrets with `fly secrets set` and attach a volume at `/data`.

---

## Troubleshooting

- **Dashboard loads but is empty** — no live data yet; wait for the first inbox
  sweep, or run with `DONNA_DEMO=1` to see it populated.
- **No push on iPhone** — iOS only allows web push for apps added to the Home
  Screen; install it first, then allow notifications.
- **Google token expired** — re-run `python scripts/setup_google.py` and update
  `GOOGLE_TOKEN_JSON`.
- **Telegram “session revoked”** — you logged the session out from a device;
  re-run `python scripts/setup_telegram.py`.
