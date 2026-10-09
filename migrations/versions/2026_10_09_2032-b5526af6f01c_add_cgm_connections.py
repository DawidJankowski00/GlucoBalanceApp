"""add cgm connections (source, encrypted follower login, polling and alert state)

Revision ID: b5526af6f01c
Revises: c5e9f3a7b124
Create Date: 2026-10-09 20:32:41.690709

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import glucobalance.models.types

# revision identifiers, used by Alembic.
revision: str = "b5526af6f01c"
down_revision: str | Sequence[str] | None = "c5e9f3a7b124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "cgm_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.Enum("librelinkup", "simulator", name="cgmsourcekind", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("poll_minutes", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("password_encrypted", sa.Text(), nullable=True),
        sa.Column("server", sa.String(length=8), nullable=False),
        sa.Column("auto_accept_terms", sa.Boolean(), nullable=False),
        sa.Column("patient_id", sa.String(length=64), nullable=True),
        sa.Column("reconnect_requested", sa.Boolean(), nullable=False),
        sa.Column("token_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "token_expires_at", glucobalance.models.types.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column("account_id", sa.String(length=64), nullable=True),
        sa.Column("region", sa.String(length=16), nullable=True),
        sa.Column("api_version", sa.String(length=16), nullable=True),
        sa.Column(
            "last_poll_at", glucobalance.models.types.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "last_success_at", glucobalance.models.types.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "last_reading_at", glucobalance.models.types.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column(
            "retry_after", glucobalance.models.types.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "alert_kind",
            sa.Enum(
                "low",
                "high",
                "falling_fast",
                "stale",
                name="glucosealertkind",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column(
            "alert_sent_at", glucobalance.models.types.UTCDateTime(timezone=True), nullable=True
        ),
        sa.CheckConstraint(
            "failure_count >= 0", name=op.f("ck_cgm_connections_failure_count_not_negative")
        ),
        sa.CheckConstraint(
            "poll_minutes BETWEEN 1 AND 5", name=op.f("ck_cgm_connections_poll_minutes_range")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_cgm_connections_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cgm_connections")),
        sa.UniqueConstraint("user_id", name=op.f("uq_cgm_connections_user_id")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("cgm_connections")
