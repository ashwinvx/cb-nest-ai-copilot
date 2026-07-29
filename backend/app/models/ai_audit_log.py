"""Audit trail for every AI copilot interaction.

One row per chat request. Deliberately has no column for tool results,
agent responses, or SQL result sets — outputs can contain payroll/bank
data, so the schema makes storing them impossible. generated_sql is
query TEXT only (valuable for auditing blocked attempts) and, like
message, must be sanitized by services.ai.audit before insert.
"""

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import Role


class AIAuditStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"  # tool/agent completed the user's request
    REFUSED = "REFUSED"  # permission denied (role gate, team scope)
    BLOCKED = "BLOCKED"  # guardrail tripped (SQL denylist, injection attempt)
    ERROR = "ERROR"      # upstream/validation failure


class AIAuditLog(Base):
    __tablename__ = "ai_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    role: Mapped[Role] = mapped_column(Enum(Role))
    endpoint: Mapped[str] = mapped_column(String(40), index=True)
    message: Mapped[str] = mapped_column(Text)
    detected_intent: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    action_status: Mapped[AIAuditStatus] = mapped_column(Enum(AIAuditStatus), index=True)
    generated_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    record_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
