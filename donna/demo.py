"""Seed realistic sample data so the dashboard is fully clickable with no
credentials. Enabled by DONNA_DEMO=1. Idempotent-ish: only seeds when empty.
"""
from __future__ import annotations

import datetime as dt

from .db import (
    ActionLog,
    Bucket,
    BucketProposal,
    Contact,
    Draft,
    DraftStatus,
    FollowUp,
    Item,
    ItemStatus,
    Priority,
    Project,
    ProjectItem,
    ProjectStatus,
    Source,
    StashItem,
    StashKind,
    StashStatus,
    Task,
    session_scope,
    utcnow,
)


def seed_demo() -> None:
    with session_scope() as s:
        if s.query(Item).count() > 0:
            return
        now = utcnow()

        vips = [
            Contact(name="Marco (ABC Trading)", email="marco@abctrading.com",
                    relationship_note="Waiting on you", is_vip=True),
            Contact(name="Tita Cora", relationship_note="New message", is_vip=True),
            Contact(name="Elena (boss)", email="elena@company.com",
                    relationship_note="All caught up", is_vip=True),
        ]
        s.add_all(vips)
        s.flush()

        i1 = Item(source=Source.gmail, external_id="demo1", thread_id="t1",
                  sender="Marco — ABC Trading", sender_contact_id=vips[0].id,
                  subject="Re: Q3 supplier contract — revised terms attached",
                  snippet="Hi — attached the revised Q3 terms. We moved the unit "
                          "price to ₱48.50 and kept the July delivery window…",
                  body="Hi,\n\nThanks for the call earlier. As agreed, I've attached "
                       "the revised Q3 supplier contract. Two changes from the last "
                       "version:\n\n1. Unit price adjusted to ₱48.50 (from ₱51.00)\n"
                       "2. July delivery window retained, with a 3-day grace period\n\n"
                       "If these look good on your end, can you sign and return so we "
                       "can lock the July slot? Our production calendar fills up fast "
                       "this quarter.\n\nBest,\nMarco\nABC Trading",
                  priority=Priority.high,
                  reason="Contract decision needed", status=ItemStatus.open,
                  created_at=now - dt.timedelta(hours=2))
        i2 = Item(source=Source.telegram, external_id="demo2", thread_id="t2",
                  sender="Tita Cora", sender_contact_id=vips[1].id,
                  subject="Pupunta ka ba sa Linggo?",
                  snippet="Anak, pupunta ka ba sa Linggo?",
                  body="Anak, pupunta ka ba sa Linggo? Handaan ni Lolo, 12nn sa bahay. "
                       "Sabi ni Mama baka raw busy ka. Pakisagot na lang para makabili "
                       "ako ng ulam. 🙏",
                  priority=Priority.normal,
                  reason="Family, quick reply", status=ItemStatus.open,
                  created_at=now - dt.timedelta(hours=11))
        i3 = Item(source=Source.gmail, external_id="demo3", thread_id="t3",
                  sender="Ana — Delgado & Co.", subject="Payment from Delgado & Co. is 12 days late",
                  snippet="Following up on invoice #4471, due July 10, still unpaid…",
                  body="Hi,\n\nApologies for the delay. We received invoice #4471 "
                       "(due July 10) but it's stuck in our approval queue while our "
                       "finance lead is on leave. I don't have a firm date yet.\n\n"
                       "Will this hold up the next shipment?\n\nThanks,\nAna",
                  priority=Priority.urgent,
                  reason="Money, overdue", status=ItemStatus.open,
                  created_at=now - dt.timedelta(days=12))
        s.add_all([i1, i2, i3])
        s.flush()

        s.add_all([
            Draft(item_id=i1.id, channel=Source.gmail, to="marco@abctrading.com",
                  status=DraftStatus.pending,
                  summary="Confirm the terms look good and ask for the signed PDF today.",
                  body="Hi Marco — the revised terms look good on our end. Could you "
                       "send the signed PDF today so we can lock the July delivery "
                       "slot? Appreciate the quick turnaround."),
            Draft(item_id=i2.id, channel=Source.telegram, to="0",
                  status=DraftStatus.pending,
                  summary="Reply yes — there by 1pm, and you'll bring dessert.",
                  body="Opo Tita, andyan ako by 1pm. Ako na bahala sa dessert 🙏"),
            Draft(item_id=i3.id, channel=Source.gmail, to="ana@delgado.com",
                  status=DraftStatus.pending,
                  summary="Ask Ana to confirm a payment date; offer to resend the invoice.",
                  body="Hi Ana — just flagging invoice #4471 (due July 10) is still "
                       "open. Could you confirm the payment date? Happy to resend the "
                       "invoice if helpful. Thanks!"),
        ])

        s.add_all([
            FollowUp(contact_name="Rina Santos", subject="Re: warehouse lease renewal",
                     thread_id="f1", last_activity=now - dt.timedelta(days=6)),
            FollowUp(contact_name="Accounting (BIR filing)", subject="Q2 docs sent",
                     thread_id="f2", last_activity=now - dt.timedelta(days=3)),
            FollowUp(contact_name="Kevin — Logistics", subject="Cebu route quote",
                     thread_id="f3", last_activity=now - dt.timedelta(days=2)),
        ])

        tasks = [
            Task(text="Review and sign the ABC Trading contract", created_by="donna"),
            Task(text="Call the accountant about the Q2 filing", created_by="you"),
            Task(text="Approve the payroll run", created_by="you", done=True),
            Task(text="Try Claude Code on the MGC ERP repo", created_by="donna"),
            Task(text="Try the Meta ads MCP server on one live campaign", created_by="donna"),
            Task(text="Try Higgsfield for a 15s LPG delivery ad", created_by="donna"),
        ]
        s.add_all(tasks)
        s.flush()

        s.add_all([
            ActionLog(summary="Archived 6 low-priority emails (receipts, newsletters)",
                      source=Source.gmail),
            ActionLog(summary="Filed 2 newsletters to 'Read later'", source=Source.gmail),
            ActionLog(summary="Confirmed your 11:30 dentist appointment",
                      source=Source.calendar),
        ])

        # ── Projects (auto-grouped) ──────────────────────────────────
        p1 = Project(
            name="Q3 Supplier Contract — ABC Trading", company="ABC Trading",
            status=ProjectStatus.needs_you,
            next_action="Get Marco's signed PDF to lock the July delivery slot.",
            owes="Marco owes you the signed contract",
            deadline=now + dt.timedelta(days=3), amount=None,
            participants=["Marco", "You"], match_keys=["abctrading.com", "Q3 contract", "Marco"],
            last_activity=now - dt.timedelta(hours=2))
        p2 = Project(
            name="Delgado & Co. — Overdue Payment", company="Delgado & Co.",
            status=ProjectStatus.needs_you,
            next_action="Approve the firm follow-up on invoice #4471 and pin a payment date.",
            owes="Ana owes you a committed payment date",
            amount="overdue 12d",
            participants=["Ana"], match_keys=["delgado", "#4471", "invoice"],
            last_activity=now - dt.timedelta(days=12))
        p3 = Project(
            name="Warehouse Lease Renewal", status=ProjectStatus.stalled,
            next_action="Nudge Rina Santos — no reply since you sent terms 6 days ago.",
            owes="Rina owes you a reply", participants=["Rina Santos"],
            match_keys=["warehouse", "lease", "Rina"],
            last_activity=now - dt.timedelta(days=6))
        p4 = Project(
            name="BIR Q2 Filing", status=ProjectStatus.on_track,
            next_action="Confirm accounting received the Q2 docs — nothing needed from you yet.",
            owes="Accounting owes confirmation", deadline=now + dt.timedelta(days=6),
            participants=["Accounting"], match_keys=["BIR", "Q2", "filing"],
            last_activity=now - dt.timedelta(days=3))
        p5 = Project(
            name="Cebu Route Launch", status=ProjectStatus.on_track,
            next_action="Review Kevin's logistics quote when it lands (expected this week).",
            owes="Kevin owes the route quote", participants=["Kevin"],
            match_keys=["Cebu", "route", "Kevin", "logistics"],
            last_activity=now - dt.timedelta(days=1))
        p6 = Project(
            name="CDV Check Requests — Masagana", created_by="monday",
            external_ref="monday:board:demo", status=ProjectStatus.needs_you,
            next_action="3 item(s) need attention on the CDV Check Request board.",
            pending=3, match_keys=["CDV", "check request"],
            last_activity=now - dt.timedelta(hours=5))
        s.add_all([p1, p2, p3, p4, p5, p6])
        s.flush()

        i1.project_id = p1.id
        i3.project_id = p2.id
        s.add_all([
            ProjectItem(project_id=p1.id, source=Source.gmail, external_id="demo1",
                        label="Revised Q3 contract from Marco"),
            ProjectItem(project_id=p1.id, source=Source.calendar, external_id="pi-abc-call",
                        label="Vendor call"),
            ProjectItem(project_id=p2.id, source=Source.gmail, external_id="demo3",
                        label="Invoice #4471 overdue"),
            ProjectItem(project_id=p3.id, source=Source.gmail, external_id="pi-lease-1",
                        label="Warehouse lease terms sent"),
            ProjectItem(project_id=p4.id, source=Source.gmail, external_id="pi-bir-1",
                        label="Q2 filing docs to accounting"),
            ProjectItem(project_id=p5.id, source=Source.telegram, external_id="pi-cebu-1",
                        label="Kevin — Cebu route chat"),
            ProjectItem(project_id=p6.id, source=Source.monday, external_id="board:demo",
                        label="CDV Check Request board"),
        ])

        # ── Stash (forwarded posts) ──────────────────────────────────
        # Three tools under one topic, which is exactly the shape that earns a
        # sub-folder proposal — so the split flow is visible on first run.
        b_cc = Bucket(kind=StashKind.tool, name="Claude Code")
        b_video = Bucket(kind=StashKind.tool, name="AI Video")
        b_hooks = Bucket(kind=StashKind.inspo, name="Short-Form Hooks")
        b_lpg = Bucket(kind=StashKind.idea, name="LPG Retail")
        b_read = Bucket(kind=StashKind.read, name="Long Reads")
        s.add_all([b_cc, b_video, b_hooks, b_lpg, b_read])
        s.flush()

        def stash(ext, title, kind, bucket, summary, why=None, platform="instagram",
                  url=None, hours=3, task=None, note=None):
            return StashItem(
                source=Source.telegram, external_id=ext,
                url=url or f"https://www.instagram.com/reel/{ext}/",
                platform=platform, title=title, summary=summary, why=why,
                raw_text=f"{title} — {summary}", note=note,
                kind=kind, bucket_id=bucket.id, confidence=0.82,
                status=StashStatus.filed, task_id=(task.id if task else None),
                created_at=now - dt.timedelta(hours=hours),
            )

        st1 = stash("saved-101", "Claude Code running a whole repo migration",
                    StashKind.tool, b_cc,
                    "A dev shows Claude Code refactoring a legacy codebase end to end.",
                    why="You've been meaning to point it at the ERP.",
                    platform="x", url="https://x.com/demo/status/101",
                    hours=4, task=tasks[3])
        st2 = stash("saved-102", "Claude Code + Meta Ads MCP",
                    StashKind.tool, b_cc,
                    "Wiring the Meta marketing API into Claude Code as an MCP server.",
                    why="Directly useful for the Masagana ad account.",
                    platform="youtube", url="https://youtu.be/demo102",
                    hours=9, task=tasks[4])
        st3 = stash("saved-103", "Auto-generating Meta ad variants from one brief",
                    StashKind.tool, b_cc,
                    "Claude Code scripted against the Meta ads library to spin 40 variants.",
                    platform="linkedin", url="https://www.linkedin.com/posts/demo103",
                    hours=26)
        st3b = stash("saved-111", "Claude Code hooks for a pre-commit reviewer",
                     StashKind.tool, b_cc,
                     "Wires a review pass into the commit hook — nothing to do with ads.",
                     platform="x", url="https://x.com/demo/status/111", hours=33)
        st4 = stash("saved-104", "Higgsfield product-video workflow",
                    StashKind.tool, b_video,
                    "Turns a single product photo into a 15-second ad.",
                    why="Cheap way to test LPG delivery creative.",
                    platform="tiktok", url="https://www.tiktok.com/@demo/video/104",
                    hours=30, task=tasks[5])
        st5 = stash("saved-105", "The 3-second problem-first hook",
                    StashKind.inspo, b_hooks,
                    "Opens on the failure state, names the cost, then the product.",
                    platform="instagram", hours=52)
        st6 = stash("saved-106", "Text-on-screen pacing for silent autoplay",
                    StashKind.inspo, b_hooks,
                    "One idea per 1.2s, no narration needed.",
                    platform="instagram", hours=70)
        st7 = stash("saved-107", "Competitor doing same-day LPG delivery tracking",
                    StashKind.idea, b_lpg,
                    "A rival is exposing live delivery ETA to customers by SMS.",
                    why="Worth costing out against our dispatch flow.",
                    platform="facebook", url="https://www.facebook.com/demo/posts/107",
                    hours=20)
        st8 = stash("saved-108", "Why most ERP rollouts stall in year two",
                    StashKind.read, b_read,
                    "Long thread on change management, not software.",
                    platform="x", url="https://x.com/demo/status/108", hours=44)
        s.add_all([st1, st2, st3, st3b, st4, st5, st6, st7, st8])
        s.flush()

        # One she genuinely couldn't read — the Instagram permalink problem.
        s.add(StashItem(
            source=Source.telegram, external_id="saved-109",
            url="https://www.instagram.com/reel/C8xK2pQrS9v/",
            platform="instagram", title="Instagram reel",
            raw_text="https://www.instagram.com/reel/C8xK2pQrS9v/",
            kind=StashKind.unsorted, confidence=0.0, status=StashStatus.asking,
            question="Nothing readable on this one — a tool to try, or inspo?",
            created_at=now - dt.timedelta(minutes=25),
        ))

        # One already judged, so "Already judged" isn't empty.
        s.add(StashItem(
            source=Source.telegram, external_id="saved-110",
            url="https://www.producthunt.com/demo110", platform="web",
            title="Yet another AI notetaker", summary="Meeting transcription with actions.",
            raw_text="notetaker", kind=StashKind.tool, bucket_id=b_video.id,
            confidence=0.9, status=StashStatus.tried,
            verdict="Meh — Otter already does this and we pay for it.",
            created_at=now - dt.timedelta(days=6),
            decided_at=now - dt.timedelta(days=4),
        ))

        s.add(BucketProposal(
            bucket_id=b_cc.id, name="Claude Code for Meta",
            rationale="Three of these are specifically about driving Meta ad accounts.",
            item_ids=[st2.id, st3.id, st1.id], status="pending",
        ))

        s.add(ActionLog(summary="Stashed “Claude Code + Meta Ads MCP” → Tools to try › Claude Code",
                        source=Source.telegram))
