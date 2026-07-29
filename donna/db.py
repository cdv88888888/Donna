"""Database layer — SQLAlchemy models and a session factory.

Every section of the dashboard is backed by one of these tables:
  Item        -> "Needs you" queue
  Draft       -> Donna's proposed replies awaiting approval
  FollowUp    -> "Waiting on a reply" tracker
  Task        -> "To-do"
  Contact     -> "From your people" (VIPs)
  ActionLog   -> "Handled for you"
  StyleProfile-> the trained voice, injected into every draft
  Watermark   -> polling bookmarks so we never re-process mail
  PushSub     -> web-push subscriptions for phone notifications
  Setting     -> runtime toggles (autonomy mode, etc.)
  Bucket      -> "Stash" folders (a topic, and the angles split out of it)
  StashItem   -> one forwarded post, filed into a bucket
  BucketProposal -> a split Donna wants to make, awaiting your yes/no
"""
from __future__ import annotations

import datetime as dt
import enum
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

from .config import settings


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


# ── Enums ────────────────────────────────────────────────────────────
class Source(str, enum.Enum):
    gmail = "gmail"
    telegram = "telegram"
    calendar = "calendar"
    monday = "monday"
    web = "web"          # pasted straight into the dashboard
    system = "system"


class Priority(str, enum.Enum):
    urgent = "urgent"
    high = "high"
    normal = "normal"
    low = "low"


class ItemStatus(str, enum.Enum):
    open = "open"        # needs you
    handled = "handled"  # Donna dealt with it (auto)
    snoozed = "snoozed"
    dismissed = "dismissed"
    done = "done"


class DraftStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    sent = "sent"
    edited = "edited"
    rejected = "rejected"


class ProjectStatus(str, enum.Enum):
    needs_you = "needs_you"   # has an open decision or deadline risk
    stalled = "stalled"       # quiet past the threshold
    on_track = "on_track"     # moving, nothing needed from you


class StashKind(str, enum.Enum):
    """The four top-level buckets a forwarded post can land in."""
    tool = "tool"          # something to go and try — the only kind that makes a to-do
    inspo = "inspo"        # content & creative worth stealing from
    idea = "idea"          # a business thought to chew on
    read = "read"          # long post / thread / video for later
    unsorted = "unsorted"  # Donna couldn't tell; she'll ask you for one line


class StashStatus(str, enum.Enum):
    filed = "filed"        # classified and sitting in its bucket
    asking = "asking"      # Donna needs a line from you before she can file it
    tried = "tried"        # you gave a verdict — archived, still searchable
    archived = "archived"


# ── Models ───────────────────────────────────────────────────────────
class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[Optional[str]] = mapped_column(String(320), index=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    relationship_note: Mapped[Optional[str]] = mapped_column(String(200))
    is_vip: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Item(Base):
    """One thing that arrived and may need the owner's attention."""
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_item_src_ext"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[Source] = mapped_column(Enum(Source))
    external_id: Mapped[str] = mapped_column(String(256))   # gmail thread id / tg msg id / event id
    thread_id: Mapped[Optional[str]] = mapped_column(String(256))
    sender: Mapped[Optional[str]] = mapped_column(String(320))
    sender_contact_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contacts.id"))
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    snippet: Mapped[Optional[str]] = mapped_column(Text)          # one-line preview
    body: Mapped[Optional[str]] = mapped_column(Text)             # full incoming message
    priority: Mapped[Priority] = mapped_column(Enum(Priority), default=Priority.normal)
    reason: Mapped[Optional[str]] = mapped_column(String(500))  # why Donna flagged it
    status: Mapped[ItemStatus] = mapped_column(Enum(ItemStatus), default=ItemStatus.open)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"))  # for per-project rollup
    snooze_until: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    drafts: Mapped[list["Draft"]] = relationship(back_populates="item", cascade="all, delete-orphan")


class Draft(Base):
    __tablename__ = "drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    channel: Mapped[Source] = mapped_column(Enum(Source))
    to: Mapped[Optional[str]] = mapped_column(String(320))
    body: Mapped[str] = mapped_column(Text)
    summary: Mapped[Optional[str]] = mapped_column(String(200))  # one-line "Donna will…"
    status: Mapped[DraftStatus] = mapped_column(Enum(DraftStatus), default=DraftStatus.pending)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[Item] = relationship(back_populates="drafts")


class FollowUp(Base):
    """A thread where the owner is waiting on someone else to reply."""
    __tablename__ = "followups"
    id: Mapped[int] = mapped_column(primary_key=True)
    contact_name: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(500))
    thread_id: Mapped[str] = mapped_column(String(256))
    source: Mapped[Source] = mapped_column(Enum(Source), default=Source.gmail)
    last_activity: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def age_days(self) -> int:
        last = self.last_activity
        if last.tzinfo is None:  # SQLite returns naive datetimes; treat as UTC
            last = last.replace(tzinfo=dt.timezone.utc)
        return (utcnow() - last).days


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(String(20), default="you")  # you | donna
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    due: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ActionLog(Base):
    """Things Donna did on her own — powers the 'Handled for you' section."""
    __tablename__ = "action_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    summary: Mapped[str] = mapped_column(String(500))
    source: Mapped[Source] = mapped_column(Enum(Source), default=Source.system)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StyleProfile(Base):
    """The trained voice. channel: 'email' | 'telegram' | 'global'."""
    __tablename__ = "style_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(20), unique=True)
    guide: Mapped[str] = mapped_column(Text)                    # distilled style guide
    examples: Mapped[list] = mapped_column(JSON, default=list)  # few-shot samples
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Watermark(Base):
    """Bookmarks so polling never re-processes the same message."""
    __tablename__ = "watermarks"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)   # e.g. "gmail_history_id"
    value: Mapped[str] = mapped_column(String(256))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PushSub(Base):
    __tablename__ = "push_subs"
    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(256))
    auth: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256))


class Project(Base):
    """A thing the owner is working on, auto-grouped from messages across sources."""
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    company: Mapped[Optional[str]] = mapped_column(String(200))
    status: Mapped[ProjectStatus] = mapped_column(Enum(ProjectStatus), default=ProjectStatus.on_track)
    next_action: Mapped[Optional[str]] = mapped_column(Text)
    owes: Mapped[Optional[str]] = mapped_column(String(300))       # "Marco owes you the signed PDF"
    deadline: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Optional[str]] = mapped_column(String(60))      # e.g. "₱2.4M", "overdue 12d"
    participants: Mapped[list] = mapped_column(JSON, default=list) # display names
    match_keys: Mapped[list] = mapped_column(JSON, default=list)   # emails / invoice#s / keywords for assignment
    created_by: Mapped[str] = mapped_column(String(20), default="donna")
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    pending: Mapped[int] = mapped_column(Integer, default=0)   # external "needs you" (e.g. Monday items)
    external_ref: Mapped[Optional[str]] = mapped_column(String(120))  # e.g. "monday:board:123"
    last_activity: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    members: Mapped[list["ProjectItem"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    @property
    def age_days(self) -> int:
        last = self.last_activity
        if last.tzinfo is None:
            last = last.replace(tzinfo=dt.timezone.utc)
        return (utcnow() - last).days


class ProjectItem(Base):
    """A message/event attached to a project (any source, whether or not it's an open Item)."""
    __tablename__ = "project_items"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_projitem_src_ext"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    source: Mapped[Source] = mapped_column(Enum(Source))
    external_id: Mapped[str] = mapped_column(String(256))
    label: Mapped[Optional[str]] = mapped_column(String(300))
    when: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="members")


# ── Stash: forwarded posts, filed into buckets ───────────────────────
class Bucket(Base):
    """A folder in the stash.

    Two levels, deliberately. A top-level bucket is a *topic* ("Claude Code");
    a child is an *angle* Donna split out of it once enough items shared one
    ("Claude Code for Meta"). Deeper than that and it stops being findable.
    """
    __tablename__ = "buckets"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[StashKind] = mapped_column(Enum(StashKind), default=StashKind.tool)
    name: Mapped[str] = mapped_column(String(160))
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("buckets.id"))
    created_by: Mapped[str] = mapped_column(String(20), default="donna")  # donna | you
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    children: Mapped[list["Bucket"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    parent: Mapped[Optional["Bucket"]] = relationship(
        back_populates="children", remote_side="Bucket.id"
    )


class StashItem(Base):
    """One thing the owner forwarded — usually a social post — plus what Donna
    made of it. `raw_text` keeps exactly what arrived, because on Instagram and
    Facebook the link alone is often all there is."""
    __tablename__ = "stash_items"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_stash_src_ext"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[Source] = mapped_column(Enum(Source), default=Source.telegram)
    external_id: Mapped[str] = mapped_column(String(256))
    url: Mapped[Optional[str]] = mapped_column(String(1000))
    platform: Mapped[Optional[str]] = mapped_column(String(40))  # instagram | x | youtube | …
    title: Mapped[Optional[str]] = mapped_column(String(300))
    summary: Mapped[Optional[str]] = mapped_column(Text)   # one line: what it is
    why: Mapped[Optional[str]] = mapped_column(Text)       # one line: why you kept it
    raw_text: Mapped[Optional[str]] = mapped_column(Text)  # exactly what you forwarded
    note: Mapped[Optional[str]] = mapped_column(String(500))     # your one-liner, if she asked
    question: Mapped[Optional[str]] = mapped_column(String(300))  # what she wants to know
    kind: Mapped[StashKind] = mapped_column(Enum(StashKind), default=StashKind.unsorted)
    bucket_id: Mapped[Optional[int]] = mapped_column(ForeignKey("buckets.id"))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[StashStatus] = mapped_column(Enum(StashStatus), default=StashStatus.filed)
    verdict: Mapped[Optional[str]] = mapped_column(String(500))  # "good, using it" / "meh"
    task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id"))  # the "try it" to-do
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))


class BucketProposal(Base):
    """Donna wants to split a topic because 3+ items in it share one angle.
    Nothing moves until you tap yes."""
    __tablename__ = "bucket_proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    bucket_id: Mapped[int] = mapped_column(ForeignKey("buckets.id"))  # the topic to split
    name: Mapped[str] = mapped_column(String(160))                    # proposed child name
    rationale: Mapped[Optional[str]] = mapped_column(String(400))
    item_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|accepted|rejected
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ── Engine / session ─────────────────────────────────────────────────
_engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(_engine)


@contextmanager
def session_scope() -> Iterator["SessionLocal"]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ── Small helpers used across skills ─────────────────────────────────
def get_setting(s, key: str, default: str | None = None) -> str | None:
    row = s.get(Setting, key)
    return row.value if row else default


def set_setting(s, key: str, value: str) -> None:
    row = s.get(Setting, key)
    if row:
        row.value = value
    else:
        s.add(Setting(key=key, value=value))


def get_watermark(s, key: str) -> str | None:
    row = s.execute(select(Watermark).where(Watermark.key == key)).scalar_one_or_none()
    return row.value if row else None


def set_watermark(s, key: str, value: str) -> None:
    row = s.execute(select(Watermark).where(Watermark.key == key)).scalar_one_or_none()
    if row:
        row.value = value
        row.updated_at = utcnow()
    else:
        s.add(Watermark(key=key, value=value))
