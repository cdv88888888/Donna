---
name: project-updates
description: >-
  Give Cholo (Chief Business & Technology Officer, Masagana Gas) a single calm
  rollup of everything moving across his projects — pulled live from his Monday
  boards, Gmail, and Google Calendar — sorted into what needs him, what's
  stalled, and what's on track, each with the one next action and who owes what.
  Use this whenever he says things like "project update", "what's the status of
  my projects", "give me the rollup", "what needs me", "what's stalled", "where
  are things", "catch me up", "morning project brief", "what's moving", "any
  updates on <project/board>", "who owes me what", or otherwise asks to see the
  state of his initiatives across sources. Also trigger it when he names one of
  his boards or workstreams (2026 Company Projects, CDV Projects/Tasks,
  Recruitment, Fleet Repairs, Guard House Renovation, Uniform Issuance, Retail
  Partner Program, MGC Website) and asks how it's going. Default to this skill
  even if he doesn't say the word "project" — the intent is "protect my
  attention: show me only what I need to act on."
---

# Project Updates

## What this does and why

Cholo gets pulled at from Monday, email, and calendar all day. His whole ask is
the opposite of another noisy inbox: **one place that tells him only what needs
him, and stays quiet about the rest.** This skill sweeps his real project
sources, decides which of three states each project is in, and hands back a
short, scannable brief he can act on in under two minutes.

The states are deliberately blunt so a glance is enough:

- **Needs you** — a decision, approval, reply, or unblock that only Cholo can do.
  This is the section he reads first; everything here has a concrete next action
  addressed to him.
- **Stalled** — no movement for a while (roughly a week+), or a due date already
  passed with the item not done. Something is quietly rotting; surface it.
- **On track** — moving on its own, owned by someone else, nothing needed from
  him. One line each, just so he knows it's alive.

Ruthlessness is the point. A long "everything's fine" list is a failure. If a
project needs nothing from him and is genuinely fine, it gets one line or gets
folded into a count ("+4 others on track"). Protect his attention like it's the
scarce resource it is.

## The sources to sweep

Everything runs on **live connectors** — the Monday, Gmail, and Google Calendar
MCP tools. Never use the browser, and never depend on any deployed backend; this
skill works entirely from the connectors available in the session.

### Monday — the project boards (primary source)

These are the boards that represent real initiatives. Pull open items from them.
Board IDs (account `masagana-gas.monday.com`):

| Board | ID | What it is |
|---|---|---|
| 2026 Company Projects | `18393004027` | The master project list — always sweep this |
| CDV Projects / Tasks | `3498017588` | Cholo's own projects/tasks |
| Recruitment pipeline | `7221738244` | Hiring in progress |
| 2026 Fleet Repairs / PMS Requisition | `1522432815` | Vehicle repair workstream |
| Guard House Renovation & Security Overhaul | `18412736022` | Active build |
| 2026 Uniform Issuance | `18410113994` | Rollout |
| MGC Retail Partner Program | `4097464571` | Partner initiative |
| MGC ASSET (Project and Plant) | `2840171546` | Asset/plant projects |

Default sweep = **2026 Company Projects + CDV Projects / Tasks** (the two true
project boards). Pull the others when Cholo names them, asks for "everything", or
when a Company Projects item clearly points at one of them. Don't drown the brief
by sweeping all eight every time unless asked.

**The CDV finance boards** (Check Request `2223545195`, Cash Advance `6537744321`,
Reimbursement/Liquidation `6528255115`, Job Service `6528474087`) are **money
sources, not projects.** Don't list their items as projects. Use them only to
answer "who owes what / what's waiting on money" — e.g. an item stuck awaiting
Cholo's approval is a **Needs you** money line. Processing check requests is a
different job (the `cdv-check-request-audit` skill) — don't do that here.

Read each board with `get_board_items_page` (`includeColumns: true`), asking only
for the columns you need: the name, a **status/color** column (state), a **person**
column (owner), a **date/timeline** column (deadline), and any **last-updated**
signal. If you don't know a board's exact column IDs, call `get_board_info` once
to learn them, then read items. Group and status labels vary board to board —
read what's there rather than assuming a fixed schema.

**Critical gotcha — status often lives in subitems, not the parent.** On the
**2026 Company Projects** board (`18393004027`) each top-level item is a *project*
and the real status/owner/date/cost live in its **subitems** (sub-board
`18393004029`, columns `status`, `person`, `date0`, `numeric_mkzvqbw5`). The
parent's mirror/lookup columns (`lookup_*`, "Owners", "Subitems Status") return
**"Column value type is not supported"** through the API — you cannot read status
from them. So on this board, pull items with `includeSubItems: true` and read the
subitem columns; roll the subitems up into one project state (any Stuck → stalled;
all Done → done; a subitem owned by Cholo and open → needs you). Don't try to sweep
all 179 at once — target the groups/items that matter, or page through.

**Freshness check.** Before trusting a board as "live", look at item dates against
today. If everything is months old (as the 2026 Company Projects board was when
last swept), say so plainly — a board that's gone quiet is itself the finding, and
the fresher signal has probably moved to email. Don't render stale dates as if
they were today's deadlines.

**The `CDV Projects / Tasks` board (`3498017588`) is stale** — its newest items are
from 2023. Skip it unless Cholo explicitly asks; it's not a current signal.

### Gmail — recent activity on live threads

Search the last ~7 days for threads that touch active projects, so the brief
reflects what actually moved, not just what's on a board. Good queries:
`newer_than:7d is:important`, plus targeted searches on project names, key
counterparties, or companies as they come up. A thread where **someone is waiting
on Cholo's reply** is a **Needs you** line. A thread where **Cholo is waiting on
someone** and it's gone quiet for days is a **who-owes-what** / possibly stalled
line. Ignore newsletters, receipts, and automated notices — they are not projects.

### Google Calendar — what's bearing down

Pull the next ~7 days of events. Tie a meeting to its project when the title or
attendees make it obvious ("Guard house walkthrough", "Retail partner sync"). A
project with a meeting in the next 48h that still has an open prep item on Cholo
is a **Needs you** ("prep before Thu 2pm"). Don't list routine calendar noise.

## How to decide each project's state

Judge from the merged picture across sources, not one field:

- **Needs you** if: an item's owner is Cholo and it's open; a status label reads
  like "Waiting for approval / For CDV / Needs decision / Blocked"; an email
  thread has a direct question or approval request to him; or a deadline is inside
  48h with his prep still open. Every Needs-you line must name the **single next
  action** as an imperative ("Approve the ₱2.4M Insular payment", "Reply to Nora
  re: uniform sizing", "Decide guard-house contractor").
- **Stalled** if: `last_activity` / last update is ~7+ days ago and the item isn't
  done; or a due date has passed and status isn't complete; or Cholo is waiting on
  someone who's gone silent. Say **how long** it's been and **who's holding it**.
- **On track** otherwise — open, owned by someone else, moving, nothing needed.

When money is involved, surface it: amount, and whether it's overdue ("₱2.4M,
approval pending 4d"). Cholo thinks in deals, deadlines, and money.

## Output — the rollup

Lead with the count that matters, then the three sections. Keep it tight; this is
read on a phone between meetings.

```
**Project rollup — <date>**   ·  🔴 <N> need you  ·  🟡 <N> stalled  ·  🟢 <N> on track

### 🔴 Needs you
- **<Project>** — <one-line next action, imperative>. <who/amount/deadline if relevant>
- ...

### 🟡 Stalled
- **<Project>** — <what's stuck>, no movement <X> days. Waiting on <who>.
- ...

### 🟢 On track  (<count>)
- **<Project>** — <one-line status>. Owner: <name>.
- (+<N> others moving, nothing needed)
```

Rules that keep it calm:

- **Needs-you first, always.** If nothing needs him, say so plainly at the top —
  that's a good day, not an empty report.
- **One line per project.** No paragraphs. If a project has three things needing
  him, that's three sub-bullets under it, still one line each.
- **Name names and numbers.** "Waiting on Sahanodin, 6 days" beats "pending".
  Amounts in ₱ unless the source says otherwise.
- **Fold the boring stuff.** Long on-track lists collapse into a count.
- End with a single optional line offering the obvious next move ("Want me to
  draft the reply to Nora, or nudge Sahanodin on the fleet items?") — only if
  there's a clear one. No filler.

## Running it on a schedule (proactive mode)

Cholo wanted Donna proactive, not just on-demand. If he asks for a **morning
brief** or "send me this every morning", offer to set up a Routine (scheduled
trigger) that runs this same sweep on weekday mornings and delivers the rollup.
Use the create-trigger tooling; keep the schedule to once each weekday morning
Manila time unless he says otherwise. Don't create a Routine unless he asks — just
offer.

## Notes and gotchas

- **Don't act, just report** — unless he asks. This skill's job is to surface and
  recommend. Drafting replies, nudging people, or moving Monday items happens only
  on his say-so (and check with him before writing to any board or sending mail).
- Board schemas differ. When a column's meaning isn't obvious, `get_board_info`
  once beats guessing; a wrong "stalled" call erodes trust fast.
- If a source is unreachable, say so in one line and give the rollup from the rest
  — a partial brief on time beats a perfect one late.
- Keep it honest: if nothing is stalled, don't invent a stalled section. Empty
  sections just disappear.
