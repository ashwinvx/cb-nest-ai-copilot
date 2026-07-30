"""add ai action claims

Revision ID: 0018_add_ai_action_claims
Revises: 0017_add_ai_audit_logs
Create Date: 2026-07-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0018_add_ai_action_claims"
down_revision: Union[str, None] = "0017_add_ai_audit_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_action_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("tool", sa.String(length=80), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_action_claims_id", "ai_action_claims", ["id"])
    op.create_index("ix_ai_action_claims_user_id", "ai_action_claims", ["user_id"])
    # Unique: this is the single-use enforcement, not just an index.
    op.create_index("ix_ai_action_claims_jti", "ai_action_claims", ["jti"], unique=True)


def downgrade() -> None:
    op.drop_table("ai_action_claims")
