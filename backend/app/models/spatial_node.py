from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SpatialNode(Base):
    __tablename__ = "spatial_nodes"

    __table_args__ = (
        UniqueConstraint(
            "model_id",
            "ifc_entity_id",
            name="uq_spatial_nodes_model_entity",
        ),
        UniqueConstraint(
            "model_id",
            "global_id",
            name="uq_spatial_nodes_model_global_id",
        ),
        CheckConstraint(
            "ifc_entity_id > 0",
            name="ck_spatial_nodes_ifc_entity_id_positive",
        ),
        Index("ix_spatial_nodes_model_id", "model_id"),
        Index("ix_spatial_nodes_parent_id", "parent_id"),
        Index("ix_spatial_nodes_model_ifc_type", "model_id", "ifc_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    model_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("ifc_models.id", ondelete="CASCADE"),
        nullable=False,
    )

    ifc_entity_id: Mapped[int] = mapped_column(Integer, nullable=False)

    global_id: Mapped[str] = mapped_column(String(64), nullable=False)

    ifc_type: Mapped[str] = mapped_column(String(64), nullable=False)

    name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    long_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    elevation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    parent_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("spatial_nodes.id", ondelete="CASCADE"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
