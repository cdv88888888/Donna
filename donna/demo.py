"""Seed realistic sample data so the dashboard is fully clickable with no
credentials. Enabled by DONNA_DEMO=1. Idempotent-ish: only seeds when empty.
"""
from __future__ import annotations

import datetime as dt

from .db import (
    ActionLog,
    Contact,
    Draft,
    DraftStatus,
    FollowUp,
    Item,
    ItemStatus,
    Priority,
    Source,
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
                  snippet="The revised terms look good…", priority=Priority.high,
                  reason="Contract decision needed", status=ItemStatus.open,
                  created_at=now - dt.timedelta(hours=2))
        i2 = Item(source=Source.telegram, external_id="demo2", thread_id="t2",
                  sender="Tita Cora", sender_contact_id=vips[1].id,
                  subject="Pupunta ka ba sa Linggo?",
                  snippet="Anak, pupunta ka ba sa Linggo?", priority=Priority.normal,
                  reason="Family, quick reply", status=ItemStatus.open,
                  created_at=now - dt.timedelta(hours=11))
        i3 = Item(source=Source.gmail, external_id="demo3", thread_id="t3",
                  sender="Invoice #4471", subject="Payment from Delgado & Co. is 12 days late",
                  snippet="Overdue 12 days", priority=Priority.urgent,
                  reason="Money, overdue", status=ItemStatus.open,
                  created_at=now - dt.timedelta(days=12))
        s.add_all([i1, i2, i3])
        s.flush()

        s.add_all([
            Draft(item_id=i1.id, channel=Source.gmail, to="marco@abctrading.com",
                  status=DraftStatus.pending,
                  body="Hi Marco — the revised terms look good on our end. Could you "
                       "send the signed PDF today so we can lock the July delivery "
                       "slot? Appreciate the quick turnaround."),
            Draft(item_id=i2.id, channel=Source.telegram, to="0",
                  status=DraftStatus.pending,
                  body="Opo Tita, andyan ako by 1pm. Ako na bahala sa dessert 🙏"),
            Draft(item_id=i3.id, channel=Source.gmail, to="ana@delgado.com",
                  status=DraftStatus.pending,
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

        s.add_all([
            Task(text="Review and sign the ABC Trading contract", created_by="donna"),
            Task(text="Call the accountant about the Q2 filing", created_by="you"),
            Task(text="Approve the payroll run", created_by="you", done=True),
        ])

        s.add_all([
            ActionLog(summary="Archived 6 low-priority emails (receipts, newsletters)",
                      source=Source.gmail),
            ActionLog(summary="Filed 2 newsletters to 'Read later'", source=Source.gmail),
            ActionLog(summary="Confirmed your 11:30 dentist appointment",
                      source=Source.calendar),
        ])
