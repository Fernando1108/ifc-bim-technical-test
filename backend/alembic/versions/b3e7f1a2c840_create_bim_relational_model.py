"""create bim relational model

Revision ID: b3e7f1a2c840
Revises: 4a1f8c2d9e07
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3e7f1a2c840"
down_revision: Union[str, None] = "4a1f8c2d9e07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TYPED_VALUE_CHECK = (
    "(value_kind = 'TEXT' AND value_text IS NOT NULL AND value_number IS NULL AND value_boolean IS NULL)"
    " OR (value_kind = 'NUMBER' AND value_text IS NULL AND value_number IS NOT NULL AND value_boolean IS NULL)"
    " OR (value_kind = 'BOOLEAN' AND value_text IS NULL AND value_number IS NULL AND value_boolean IS NOT NULL)"
    " OR (value_kind = 'NULL' AND value_text IS NULL AND value_number IS NULL AND value_boolean IS NULL)"
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Add counters to ifc_models
    # ------------------------------------------------------------------
    op.add_column(
        "ifc_models",
        sa.Column(
            "spatial_node_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "ifc_models",
        sa.Column(
            "element_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "ifc_models",
        sa.Column(
            "property_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # ------------------------------------------------------------------
    # 2. CHECK constraints on new counters
    # ------------------------------------------------------------------
    op.create_check_constraint(
        "ck_ifc_models_spatial_node_count_nonnegative",
        "ifc_models",
        "spatial_node_count >= 0",
    )
    op.create_check_constraint(
        "ck_ifc_models_element_count_nonnegative",
        "ifc_models",
        "element_count >= 0",
    )
    op.create_check_constraint(
        "ck_ifc_models_property_count_nonnegative",
        "ifc_models",
        "property_count >= 0",
    )

    # ------------------------------------------------------------------
    # 3. Create spatial_nodes
    # ------------------------------------------------------------------
    op.create_table(
        "spatial_nodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("ifc_entity_id", sa.Integer(), nullable=False),
        sa.Column("global_id", sa.String(length=64), nullable=False),
        sa.Column("ifc_type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("long_name", sa.String(length=512), nullable=True),
        sa.Column("elevation", sa.Float(), nullable=True),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["ifc_models.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["spatial_nodes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_id",
            "ifc_entity_id",
            name="uq_spatial_nodes_model_entity",
        ),
        sa.UniqueConstraint(
            "model_id",
            "global_id",
            name="uq_spatial_nodes_model_global_id",
        ),
        sa.CheckConstraint(
            "ifc_entity_id > 0",
            name="ck_spatial_nodes_ifc_entity_id_positive",
        ),
    )
    op.create_index("ix_spatial_nodes_model_id", "spatial_nodes", ["model_id"])
    op.create_index("ix_spatial_nodes_parent_id", "spatial_nodes", ["parent_id"])
    op.create_index(
        "ix_spatial_nodes_model_ifc_type",
        "spatial_nodes",
        ["model_id", "ifc_type"],
    )

    # ------------------------------------------------------------------
    # 4. Create elements
    # ------------------------------------------------------------------
    op.create_table(
        "elements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("ifc_entity_id", sa.Integer(), nullable=False),
        sa.Column("global_id", sa.String(length=64), nullable=False),
        sa.Column("ifc_type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("object_type", sa.String(length=512), nullable=True),
        sa.Column("tag", sa.String(length=255), nullable=True),
        sa.Column("predefined_type", sa.String(length=128), nullable=True),
        sa.Column("type_global_id", sa.String(length=64), nullable=True),
        sa.Column("type_ifc_type", sa.String(length=64), nullable=True),
        sa.Column("type_name", sa.String(length=512), nullable=True),
        sa.Column("direct_spatial_node_id", sa.Integer(), nullable=True),
        sa.Column("resolved_storey_id", sa.Integer(), nullable=True),
        sa.Column("parent_element_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["ifc_models.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["direct_spatial_node_id"],
            ["spatial_nodes.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_storey_id"],
            ["spatial_nodes.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_element_id"],
            ["elements.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_id",
            "ifc_entity_id",
            name="uq_elements_model_entity",
        ),
        sa.UniqueConstraint(
            "model_id",
            "global_id",
            name="uq_elements_model_global_id",
        ),
        sa.CheckConstraint(
            "ifc_entity_id > 0",
            name="ck_elements_ifc_entity_id_positive",
        ),
    )
    op.create_index("ix_elements_model_id", "elements", ["model_id"])
    op.create_index(
        "ix_elements_direct_spatial_node_id",
        "elements",
        ["direct_spatial_node_id"],
    )
    op.create_index(
        "ix_elements_resolved_storey_id",
        "elements",
        ["resolved_storey_id"],
    )
    op.create_index(
        "ix_elements_parent_element_id",
        "elements",
        ["parent_element_id"],
    )
    op.create_index(
        "ix_elements_model_ifc_type",
        "elements",
        ["model_id", "ifc_type"],
    )

    # ------------------------------------------------------------------
    # 5. Create element_properties
    # ------------------------------------------------------------------
    op.create_table(
        "element_properties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("element_id", sa.Integer(), nullable=False),
        sa.Column("group_type", sa.String(length=16), nullable=False),
        sa.Column("group_name", sa.String(length=255), nullable=False),
        sa.Column("property_name", sa.String(length=255), nullable=False),
        sa.Column("value_kind", sa.String(length=16), nullable=False),
        sa.Column("ifc_value_type", sa.String(length=64), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_number", sa.Float(), nullable=True),
        sa.Column("value_boolean", sa.Boolean(), nullable=True),
        sa.Column("unit", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["element_id"],
            ["elements.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "group_type IN ('PSET', 'QTO')",
            name="ck_element_properties_group_type",
        ),
        sa.CheckConstraint(
            "value_kind IN ('TEXT', 'NUMBER', 'BOOLEAN', 'NULL')",
            name="ck_element_properties_value_kind",
        ),
        sa.CheckConstraint(
            _TYPED_VALUE_CHECK,
            name="ck_element_properties_typed_value",
        ),
    )
    op.create_index(
        "ix_element_properties_element_id",
        "element_properties",
        ["element_id"],
    )
    op.create_index(
        "ix_element_properties_property_name",
        "element_properties",
        ["property_name"],
    )
    op.create_index(
        "ix_element_properties_group",
        "element_properties",
        ["group_type", "group_name"],
    )


def downgrade() -> None:
    # element_properties
    op.drop_index("ix_element_properties_group", table_name="element_properties")
    op.drop_index(
        "ix_element_properties_property_name", table_name="element_properties"
    )
    op.drop_index(
        "ix_element_properties_element_id", table_name="element_properties"
    )
    op.drop_table("element_properties")

    # elements
    op.drop_index("ix_elements_model_ifc_type", table_name="elements")
    op.drop_index("ix_elements_parent_element_id", table_name="elements")
    op.drop_index("ix_elements_resolved_storey_id", table_name="elements")
    op.drop_index("ix_elements_direct_spatial_node_id", table_name="elements")
    op.drop_index("ix_elements_model_id", table_name="elements")
    op.drop_table("elements")

    # spatial_nodes
    op.drop_index("ix_spatial_nodes_model_ifc_type", table_name="spatial_nodes")
    op.drop_index("ix_spatial_nodes_parent_id", table_name="spatial_nodes")
    op.drop_index("ix_spatial_nodes_model_id", table_name="spatial_nodes")
    op.drop_table("spatial_nodes")

    # ifc_models counters
    op.drop_constraint(
        "ck_ifc_models_property_count_nonnegative", "ifc_models", type_="check"
    )
    op.drop_constraint(
        "ck_ifc_models_element_count_nonnegative", "ifc_models", type_="check"
    )
    op.drop_constraint(
        "ck_ifc_models_spatial_node_count_nonnegative", "ifc_models", type_="check"
    )
    op.drop_column("ifc_models", "property_count")
    op.drop_column("ifc_models", "element_count")
    op.drop_column("ifc_models", "spatial_node_count")
