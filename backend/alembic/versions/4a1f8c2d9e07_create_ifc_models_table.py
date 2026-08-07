"""create ifc_models table

Revision ID: 4a1f8c2d9e07
Revises: 23c0703b5bba
Create Date: 2026-08-06 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "4a1f8c2d9e07"
down_revision: Union[str, None] = "23c0703b5bba"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ifc_models",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("ifc_schema", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "processing_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_path", name="uq_ifc_models_storage_path"),
        sa.CheckConstraint(
            "file_size_bytes > 0",
            name="ck_ifc_models_file_size_positive",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="ck_ifc_models_status",
        ),
    )
    op.create_index("ix_ifc_models_owner_id", "ifc_models", ["owner_id"])
    op.create_index("ix_ifc_models_status", "ifc_models", ["status"])
    op.create_index("ix_ifc_models_sha256", "ifc_models", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_ifc_models_sha256", table_name="ifc_models")
    op.drop_index("ix_ifc_models_status", table_name="ifc_models")
    op.drop_index("ix_ifc_models_owner_id", table_name="ifc_models")
    op.drop_table("ifc_models")
