"""add ai audit logs

Revision ID: 0017_add_ai_audit_logs
Revises: 0016_employee_documents_uploaded_by
Create Date: 2026-07-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0017_add_ai_audit_logs"
down_revision: Union[str, None] = "0016_employee_documents_uploaded_by"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("role", sa.Enum("ADMIN", "MANAGER", "EMPLOYEE", name="role", native_enum=False), nullable=False),
        sa.Column("endpoint", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("detected_intent", sa.String(length=80), nullable=True),
        sa.Column("tool_name", sa.String(length=80), nullable=True),
        sa.Column(
            "action_status",
            sa.Enum("SUCCESS", "REFUSED", "BLOCKED", "ERROR", name="aiauditstatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column("record_ids", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
    )
    op.create_index("ix_ai_audit_logs_id", "ai_audit_logs", ["id"])
    op.create_index("ix_ai_audit_logs_created_at", "ai_audit_logs", ["created_at"])
    op.create_index("ix_ai_audit_logs_user_id", "ai_audit_logs", ["user_id"])
    op.create_index("ix_ai_audit_logs_endpoint", "ai_audit_logs", ["endpoint"])
    op.create_index("ix_ai_audit_logs_tool_name", "ai_audit_logs", ["tool_name"])
    op.create_index("ix_ai_audit_logs_action_status", "ai_audit_logs", ["action_status"])


def downgrade() -> None:
    op.drop_table("ai_audit_logs")
