"""add reminder rules, notifications, push subscriptions and quiet hours

Revision ID: c5e9f3a7b124
Revises: b4d8e2f6a013
Create Date: 2026-10-09 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import glucobalance.models.types

# revision identifiers, used by Alembic.
revision: str = "c5e9f3a7b124"
down_revision: str | Sequence[str] | None = "b4d8e2f6a013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("reminders", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "rule_type",
                sa.Enum(
                    "every_n_days",
                    "daily_at",
                    "after_event",
                    name="ruletype",
                    native_enum=False,
                    length=32,
                ),
                server_default="every_n_days",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("delay_minutes", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "last_done_at", glucobalance.models.types.UTCDateTime(timezone=True), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column(
                "snoozed_until",
                glucobalance.models.types.UTCDateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_reminders_delay_not_negative"),
            "delay_minutes IS NULL OR delay_minutes >= 0",
        )

    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("quiet_start", sa.Time(), nullable=True))
        batch_op.add_column(sa.Column("quiet_end", sa.Time(), nullable=True))

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("reminder_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "created_at", glucobalance.models.types.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column("read_at", glucobalance.models.types.UTCDateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["reminder_id"],
            ["reminders.id"],
            name=op.f("fk_notifications_reminder_id_reminders"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_notifications_user_id"), ["user_id"], unique=False)

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(length=255), nullable=False),
        sa.Column("auth", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", glucobalance.models.types.UTCDateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_push_subscriptions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_subscriptions")),
        sa.UniqueConstraint("endpoint", name=op.f("uq_push_subscriptions_endpoint")),
    )
    with op.batch_alter_table("push_subscriptions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_push_subscriptions_user_id"), ["user_id"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("push_subscriptions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_push_subscriptions_user_id"))
    op.drop_table("push_subscriptions")

    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_notifications_user_id"))
    op.drop_table("notifications")

    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.drop_column("quiet_end")
        batch_op.drop_column("quiet_start")

    with op.batch_alter_table("reminders", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_reminders_delay_not_negative"), type_="check")
        batch_op.drop_column("snoozed_until")
        batch_op.drop_column("last_done_at")
        batch_op.drop_column("delay_minutes")
        batch_op.drop_column("rule_type")
