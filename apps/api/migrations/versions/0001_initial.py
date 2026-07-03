"""initial schema: postgis + users/fields/land_reports/plans/layouts

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-03
"""
from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("phone", name="uq_users_phone"),
    )
    op.create_index("ix_users_phone", "users", ["phone"])

    op.create_table(
        "fields",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.Geometry(
                geometry_type="POLYGON", srid=4326, spatial_index=False
            ),
            nullable=False,
        ),
        sa.Column("area_m2", sa.Float(), nullable=True),
        sa.Column("region", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_fields_owner_id", "fields", ["owner_id"])
    op.create_index(
        "ix_fields_geom", "fields", ["geom"], postgresql_using="gist"
    )

    for tbl, extra in (
        ("land_reports", []),
        ("plans", [sa.Column("name", sa.String(length=160), nullable=True)]),
        ("layouts", []),
    ):
        op.create_table(
            tbl,
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("field_id", sa.String(), nullable=False),
            *extra,
            sa.Column("data", postgresql.JSONB(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["field_id"], ["fields.id"], ondelete="CASCADE"
            ),
        )
        op.create_index(f"ix_{tbl}_field_id", tbl, ["field_id"])


def downgrade() -> None:
    for tbl in ("layouts", "plans", "land_reports"):
        op.drop_index(f"ix_{tbl}_field_id", table_name=tbl)
        op.drop_table(tbl)
    op.drop_index("ix_fields_geom", table_name="fields")
    op.drop_index("ix_fields_owner_id", table_name="fields")
    op.drop_table("fields")
    op.drop_index("ix_users_phone", table_name="users")
    op.drop_table("users")
