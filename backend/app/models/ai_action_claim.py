"""Single-use claims for AI pending-action tokens.

One row per consumed action token. The UNIQUE constraint on `jti` is
the enforcement mechanism: consuming a token means inserting its jti,
so a second attempt fails at the database level regardless of timing
or how many workers are running. Declining consumes the token too — a
declined action must not be replayable as an approval.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AIActionClaim(Base):
    __tablename__ = "ai_action_claims"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    tool: Mapped[str] = mapped_column(String(80))
    decision: Mapped[str] = mapped_column(String(16))  # APPROVED | DECLINED
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
