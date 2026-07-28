# Donna

Your own proactive executive assistant — trained on how *you* actually
communicate, surfacing only what needs you, on one calm screen.

Donna reads your Gmail, Google Calendar, and Telegram, triages the noise,
drafts replies in your voice, watches your calendar, and chases your
follow-ups. She reports to you through a single **focus dashboard** (installable
as a phone app) instead of yet another cluttered inbox.

> **The idea in one line:** *"127 things came in. I handled 9. Four need you."*

---

## What she does

| Behavior | How it works |
|---|---|
| **Inbox triage** | Every incoming email is classified by Claude. Noise is archived (never deleted) and logged under *Handled*; only what needs you surfaces. |
| **Drafts in your voice** | Replies are pre-written in your style, learned from your real sent mail and Telegram history. You approve with one tap — nothing sends on its own. |
| **Calendar** | She spots conflicts and proposes fixes; per your setup she can act on the calendar automatically. |
| **Follow-ups** | Threads you're owed a reply on are tracked and aged, with a one-tap nudge. |
| **Morning brief** | A short, warm "here's your day" pushed to your phone each morning. |
| **VIPs** | Anything from your key people jumps the queue regardless of the rules. |

## How it's built

A single always-on Python service:

```
┌─────────────────────────────────────────────────────────┐
│  Donna (one process)                                     │
│                                                          │
│  FastAPI  ──►  Focus dashboard (PWA + web push)          │
│  Scheduler ──► inbox sweep · brief · conflicts · nudges  │
│  Telethon ──►  live Telegram DM listener                 │
│                                                          │
│  Brain: Claude (Opus = drafting, Sonnet = triage)        │
│  Data:  SQLite (items, drafts, voice profile, …)         │
└─────────────────────────────────────────────────────────┘
        │            │             │
     Gmail API   Calendar API   Telegram (as you)
```

- **Interface:** a custom, minimal dashboard — *not* another chat app. Gmail and
  Telegram stay purely as sources she reaches into; you never have to open them.
- **Safety:** comms are **draft-and-approve** by default. The only autonomous
  actions are archiving low-value mail and (optionally) calendar ops. Secrets
  live only in deployment config — never in code or git.

## Try it right now (no accounts needed)

```bash
pip install -r requirements.txt
DONNA_DEMO=1 python -m donna.main
# open http://localhost:8000
```

Demo mode seeds realistic sample data so you can click through the whole
dashboard — approve a draft, dismiss an item, check off a task.

## Make it real

See **[docs/SETUP.md](docs/SETUP.md)** for the full step-by-step: getting an
Anthropic key, authorizing Gmail/Calendar, logging in the Telegram userbot,
generating push keys, training your voice, and deploying to Railway.

The short version:

```bash
cp .env.example .env                 # fill in the values as you go
python scripts/setup_google.py       # authorize Gmail + Calendar
python scripts/setup_telegram.py     # log in the Telegram userbot
python scripts/setup_push.py         # generate phone-push keys
python scripts/train_voice.py        # learn your writing voice
python -m donna.main                 # run her
```

## Project layout

```
donna/
  config.py          settings from env (secrets only)
  db.py              SQLAlchemy models — one table per dashboard section
  brain.py           Claude: triage() + draft()
  voice.py           distills your style guide from real messages
  notify.py          web push
  scheduler.py       the proactive loops
  api.py             FastAPI: dashboard state + actions
  main.py            entrypoint (web + scheduler + telegram)
  integrations/      gmail, gcal, telegram_user
  skills/            ingest (triage), scheduling, followups, brief, commands
web/                 the PWA (index.html, app.js, sw.js, manifest, icon)
scripts/             one-time setup + voice training
```

## Status

v0.1 — functional foundation, demo-tested end to end. Real-world reply
detection for follow-ups and richer command-bar actions are the natural next
steps; the structure is built to grow into them.
