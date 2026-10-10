"""add assistant messages and adjustment suggestions

Revision ID: eb3337bbb88f
Revises: b5526af6f01c
Create Date: 2026-10-10 10:48:35.240747

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import glucobalance.models.types

# revision identifiers, used by Alembic.
revision: str = "eb3337bbb88f"
down_revision: str | Sequence[str] | None = "b5526af6f01c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "adjustment_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", glucobalance.models.types.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column("pattern", sa.String(length=32), nullable=False),
        sa.Column("block_start", sa.Time(), nullable=False),
        sa.Column("setting", sa.String(length=8), nullable=False),
        sa.Column("current_value", sa.Numeric(precision=6, scale=1), nullable=False),
        sa.Column("proposed_value", sa.Numeric(precision=6, scale=1), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "accepted",
                "rejected",
                name="suggestionstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "resolved_at", glucobalance.models.types.UTCDateTime(timezone=True), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_adjustment_suggestions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_adjustment_suggestions")),
    )
    with op.batch_alter_table("adjustment_suggestions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_adjustment_suggestions_user_id"), ["user_id"], unique=False
        )

    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", glucobalance.models.types.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "role",
            sa.Enum("user", "assistant", name="messagerole", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("blocked", sa.Boolean(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_assistant_messages_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_messages")),
    )
    with op.batch_alter_table("assistant_messages", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_assistant_messages_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_assistant_messages_user_id"), ["user_id"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("assistant_messages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assistant_messages_user_id"))
        batch_op.drop_index(batch_op.f("ix_assistant_messages_created_at"))

    op.drop_table("assistant_messages")
    with op.batch_alter_table("adjustment_suggestions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_adjustment_suggestions_user_id"))

    op.drop_table("adjustment_suggestions")
