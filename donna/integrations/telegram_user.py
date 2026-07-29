"""Telegram userbot (Telethon) — logs in AS the owner.

Powers four things:
  - reads recent DM history to TRAIN Donna's chat voice
  - watches incoming DMs so Donna can triage them like email
  - watches Saved Messages, which is where the owner forwards social posts
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
from telethon.tl.types import MessageMediaWebPage, User, WebPage

from ..config import settings


@dataclass
class TgMessage:
    id: int
    chat_id: int
    sender_id: int
    sender_name: str
    text: str
    outgoing: bool


@dataclass
class TgSaved:
    """Something the owner dropped in Saved Messages.

    Telegram's link preview is the single best signal we get — for X, YouTube,
    TikTok and LinkedIn it carries the real title and description. Instagram and
    Facebook usually give nothing, which is exactly the case Donna has to ask about.
    """
    id: int
    chat_id: int
    text: str
    url: Optional[str] = None
    preview_title: Optional[str] = None
    preview_desc: Optional[str] = None
    forwarded_from: Optional[str] = None


_client: Optional[TelegramClient] = None
_own_id: Optional[int] = None


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


async def own_id() -> int:
    """The owner's own user id — cached, because it gates every outgoing event."""
    global _own_id
    if _own_id is None:
        _own_id = (await get_client().get_me()).id
    return _own_id


def on_saved_message(handler: Callable[[TgSaved], Awaitable[None]]) -> None:
    """Register an async handler for Saved Messages — the owner's stash inbox.

    Saved Messages is the chat with yourself, so these arrive as *outgoing*
    events. The chat id check is what separates them from a reply Donna sends on
    the owner's behalf in someone else's chat.
    """
    client = get_client()

    @client.on(events.NewMessage(outgoing=True))
    async def _dispatch(event):  # noqa: ANN001
        me = await own_id()
        if event.chat_id != me:
            return

        url = title = desc = None
        media = getattr(event.message, "media", None)
        if isinstance(media, MessageMediaWebPage) and isinstance(media.webpage, WebPage):
            url = media.webpage.url
            title = media.webpage.title
            desc = media.webpage.description

        fwd = getattr(event.message, "fwd_from", None)
        from_name = getattr(fwd, "from_name", None) if fwd else None

        await handler(TgSaved(
            id=event.id, chat_id=event.chat_id, text=event.raw_text or "",
            url=url, preview_title=title, preview_desc=desc, forwarded_from=from_name,
        ))
