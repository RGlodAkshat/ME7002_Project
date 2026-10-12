"""Platform persistence. Legacy manufacturing tables are retained as archives."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class Configuration(Base):
    __tablename__ = "platform_configuration"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    specification: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class User(Base):
    __tablename__ = "platform_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20))
    skills: Mapped[list] = mapped_column(JSON, default=list)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LoginSession(Base):
    __tablename__ = "platform_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id"))
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Order(Base):
    __tablename__ = "platform_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_name: Mapped[str] = mapped_column(String(120))
    product_id: Mapped[str] = mapped_column(String(120))
    product_name: Mapped[str] = mapped_column(String(200))
    selections: Mapped[dict] = mapped_column(JSON)
    configuration_revision: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    path_id: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Task(Base):
    __tablename__ = "platform_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    order_id: Mapped[str] = mapped_column(ForeignKey("platform_orders.id"), index=True)
    stage_id: Mapped[str] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    required_skills: Mapped[list] = mapped_column(JSON, default=list)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(40), default="queued")
    assigned_operator_id: Mapped[str | None] = mapped_column(ForeignKey("platform_users.id"), nullable=True)
    machine_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    machine_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    dispatch_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    verification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    scrap_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    command_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class MachineState(Base):
    __tablename__ = "platform_machine_state"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="available")


class Evidence(Base):
    __tablename__ = "platform_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("platform_tasks.id"), index=True)
    file_path: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Review(Base):
    __tablename__ = "platform_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("platform_tasks.id"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)


class MachineEvent(Base):
    __tablename__ = "platform_machine_events"
    external_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36))
    machine_id: Mapped[str] = mapped_column(String(120))
    event: Mapped[str] = mapped_column(String(20))
    dispatch_id: Mapped[str] = mapped_column(String(36))


class ConfigurationChange(Base):
    __tablename__ = "platform_configuration_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, unique=True)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
