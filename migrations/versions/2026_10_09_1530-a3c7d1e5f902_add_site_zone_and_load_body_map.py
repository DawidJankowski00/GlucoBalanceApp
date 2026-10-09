"""add site zone and load the body map

Revision ID: a3c7d1e5f902
Revises: e94218bd9b7f
Create Date: 2026-10-09 15:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from glucobalance.sitemap import SITES

# revision identifiers, used by Alembic.
revision: str = "a3c7d1e5f902"
down_revision: str | Sequence[str] | None = "e94218bd9b7f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the zone column, then insert every site of the body map that is missing."""
    with op.batch_alter_table("body_sites") as batch:
        batch.add_column(sa.Column("zone", sa.String(length=30), server_default="", nullable=False))

    bind = op.get_bind()
    existing = {row[0] for row in bind.execute(sa.text("SELECT code FROM body_sites"))}
    insert = sa.text(
        "INSERT INTO body_sites (code, region, side, view, zone) "
        "VALUES (:code, :region, :side, :view, :zone)"
    )
    for site in SITES:
        if site.code not in existing:
            bind.execute(
                insert,
                {
                    "code": site.code,
                    "region": site.region.value,
                    "side": site.side.value,
                    "view": site.view.value,
                    "zone": site.zone,
                },
            )


def downgrade() -> None:
    """Drop the zone column (the sites stay; they are reference data)."""
    with op.batch_alter_table("body_sites") as batch:
        batch.drop_column("zone")
