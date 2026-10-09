from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(index=True)
    action_summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActivityRun(Base):
    __tablename__ = "activity_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    goal: Mapped[str] = mapped_column(Text)
    agent: Mapped[str] = mapped_column(String(64))
    permission_level: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(32), index=True)
    summary: Mapped[str] = mapped_column(Text)
    approval_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class MemoryItem(Base):
    __tablename__ = "memory_items"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    category: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CareerProfileRecord(Base):
    __tablename__ = "career_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class MasterResumeVersion(Base):
    __tablename__ = "master_resume_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    change_note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class JobListing(Base):
    __tablename__ = "job_listings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    canonical_url: Mapped[str] = mapped_column(String(2000), unique=True, index=True)
    company: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(500), index=True)
    location: Mapped[str] = mapped_column(String(500), default="")
    work_mode: Mapped[str] = mapped_column(String(80), default="")
    url: Mapped[str] = mapped_column(String(2000))
    application_url: Mapped[str] = mapped_column(String(2000))
    description: Mapped[str] = mapped_column(Text, default="")
    requirements: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    required_skills: Mapped[list] = mapped_column(JSON, default=list)
    preferred_skills: Mapped[list] = mapped_column(JSON, default=list)
    experience: Mapped[str] = mapped_column(String(240), default="")
    salary: Mapped[str] = mapped_column(String(240), default="")
    source: Mapped[str] = mapped_column(String(100))
    posted_date: Mapped[str] = mapped_column(String(40), default="")
    match_score: Mapped[int] = mapped_column(default=0, index=True)
    match_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class LocalAction(Base):
    __tablename__ = "local_actions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(32))
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    summary: Mapped[str] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
