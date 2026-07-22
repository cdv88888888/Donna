"""Telegram userbot (Telethon) — logs in AS the owner.

Powers three things:
  - reads recent DM history to TRAIN Donna's chat voice
  - watches incoming DMs so Donna can triage them like email
  - sends replies as the owner, but only after approval

SECURITY: the session string can act as the owner's Telegram account. It lives
only in the TELEGRAM_SESSION secret, never in code or git. Donna only reads/acts
on 1:1 chats and ignores its own outgoing messages.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import User

from ..config import settings


@dataclass
class TgMessage:
    id: int
    chat_id: int
    sender_id: int
    sender_name: str
    text: str
    outgoing: bool


_client: Optional[TelegramClient] = None


def get_client() -> TelegramClient:
    global _client
    if _client is None:
        _client = TelegramClient(
            StringSession(settings.telegram_session),
            settings.telegram_api_id,
            settings.telegram_api_hash,
        )
    return _client


async def fetch_history(limit_per_chat: int = 40, max_chats: int = 25) -> list[TgMessage]:
    """Recent messages the owner SENT across 1:1 chats — chat voice training."""
    client = get_client()
    out: list[TgMessage] = []
    async for dialog in client.iter_dialogs(limit=max_chats):
        if not dialog.is_user:
            continue
        async for msg in client.iter_messages(dialog.id, limit=limit_per_chat):
            if msg.out and msg.message:
                out.append(
                    TgMessage(
                        id=msg.id, chat_id=dialog.id, sender_id=0,
                        sender_name="me", text=msg.message, outgoing=True,
                    )
                )
    return out


async def send_message(chat_id: int, text: str) -> None:
    await get_client().send_message(chat_id, text)


async def contact_name(chat_id: int) -> str:
    entity = await get_client().get_entity(chat_id)
    if isinstance(entity, User):
        return " ".join(filter(None, [entity.first_name, entity.last_name])) or "Unknown"
    return getattr(entity, "title", "Unknown")


def on_new_dm(handler: Callable[[TgMessage], Awaitable[None]]) -> None:
    """Register an async handler for incoming 1:1 messages (not from the owner)."""
    client = get_client()

    @client.on(events.NewMessage(incoming=True))
    async def _dispatch(event):  # noqa: ANN001
        if not event.is_private:
            return
        sender = await event.get_sender()
        name = " ".join(filter(None, [
            getattr(sender, "first_name", None), getattr(sender, "last_name", None)
        ])) or "Unknown"
        await handler(TgMessage(
            id=event.id, chat_id=event.chat_id, sender_id=sender.id,
            sender_name=name, text=event.raw_text or "", outgoing=False,
        ))
