"""add site blocks, site preferences and rotation settings

Revision ID: b4d8e2f6a013
Revises: a3c7d1e5f902
Create Date: 2026-10-09 15:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import glucobalance.models.types

# revision identifiers, used by Alembic.
revision: str = "b4d8e2f6a013"
down_revision: str | Sequence[str] | None = "a3c7d1e5f902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "site_blocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column(
            "blocked_at", glucobalance.models.types.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column("until", glucobalance.models.types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(
            ["site_id"], ["body_sites.id"], name=op.f("fk_site_blocks_site_id_body_sites")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_site_blocks_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_blocks")),
    )
    with op.batch_alter_table("site_blocks", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_site_blocks_user_id"), ["user_id"], unique=False)

    op.create_table(
        "site_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=2, scale=1), nullable=False),
        sa.CheckConstraint(
            "weight >= 0 AND weight <= 2", name=op.f("ck_site_preferences_weight_range")
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["body_sites.id"], name=op.f("fk_site_preferences_site_id_body_sites")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_site_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_preferences")),
        sa.UniqueConstraint("user_id", "site_id", name=op.f("uq_site_preferences_user_id")),
    )
    with op.batch_alter_table("site_preferences", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_site_preferences_user_id"), ["user_id"], unique=False)

    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("site_rest_days", sa.Integer(), server_default="14", nullable=False)
        )
        batch_op.add_column(
            sa.Column("set_change_days", sa.Integer(), server_default="3", nullable=False)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.drop_column("set_change_days")
        batch_op.drop_column("site_rest_days")

    with op.batch_alter_table("site_preferences", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_site_preferences_user_id"))
    op.drop_table("site_preferences")

    with op.batch_alter_table("site_blocks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_site_blocks_user_id"))
    op.drop_table("site_blocks")
