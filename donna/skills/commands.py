"""Command bar — natural-language commands from the dashboard.

Donna interprets a free-text instruction against the current state and either
answers or performs a small action (add a task, snooze an item, draft a reply).
Kept intentionally simple: a single tool-router prompt that returns a JSON
intent, executed here. Extend `INTENTS` as you add capabilities.
"""
from __future__ import annotations

import json

from ..config import settings
from ..db import Item, ItemStatus, Task, session_scope
from .. import brain

ROUTER_SYSTEM = """You are Donna's command router. Map the owner's instruction to \
ONE intent as JSON. Valid intents:
  {"intent":"add_task","text":"..."}
  {"intent":"snooze_item","item_id":N,"days":N}
  {"intent":"answer","text":"a direct helpful answer"}
Return ONLY the JSON object."""


def handle(instruction: str) -> str:
    with session_scope() as s:
        open_items = s.query(Item).filter(Item.status == ItemStatus.open).all()
        context = "\n".join(f"item {i.id}: {i.subject}" for i in open_items[:15])

    raw = brain.ask(
        system=ROUTER_SYSTEM,
        user=f"State:\n{context}\n\nInstruction: {instruction}",
        model=settings.model_triage,
        max_tokens=400,
    )
    try:
        start, end = raw.find("{"), raw.rfind("}")
        intent = json.loads(raw[start : end + 1])
    except Exception:
        return "Sorry, I didn't catch that — try rephrasing?"

    kind = intent.get("intent")
    if kind == "add_task":
        with session_scope() as s:
            s.add(Task(text=intent["text"], created_by="you"))
        return f"Added to your to-do: {intent['text']}"
    if kind == "snooze_item":
        with session_scope() as s:
            item = s.get(Item, intent["item_id"])
            if item:
                item.status = ItemStatus.snoozed
        return f"Snoozed for {intent.get('days', 1)} day(s)."
    return intent.get("text", "Done.")
