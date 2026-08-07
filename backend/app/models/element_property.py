from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_TYPED_VALUE_CHECK = (
    "(value_kind = 'TEXT' AND value_text IS NOT NULL AND value_number IS NULL AND value_boolean IS NULL)"
    " OR (value_kind = 'NUMBER' AND value_text IS NULL AND value_number IS NOT NULL AND value_boolean IS NULL)"
    " OR (value_kind = 'BOOLEAN' AND value_text IS NULL AND value_number IS NULL AND value_boolean IS NOT NULL)"
    " OR (value_kind = 'NULL' AND value_text IS NULL AND value_number IS NULL AND value_boolean IS NULL)"
)


class ElementProperty(Base):
    __tablename__ = "element_properties"

    __table_args__ = (
        CheckConstraint(
            "group_type IN ('PSET', 'QTO')",
            name="ck_element_properties_group_type",
        ),
        CheckConstraint(
            "value_kind IN ('TEXT', 'NUMBER', 'BOOLEAN', 'NULL')",
            name="ck_element_properties_value_kind",
        ),
        CheckConstraint(
            _TYPED_VALUE_CHECK,
            name="ck_element_properties_typed_value",
        ),
        Index("ix_element_properties_element_id", "element_id"),
        Index("ix_element_properties_property_name", "property_name"),
        Index("ix_element_properties_group", "group_type", "group_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    element_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("elements.id", ondelete="CASCADE"),
        nullable=False,
    )

    group_type: Mapped[str] = mapped_column(String(16), nullable=False)

    group_name: Mapped[str] = mapped_column(String(255), nullable=False)

    property_name: Mapped[str] = mapped_column(String(255), nullable=False)

    value_kind: Mapped[str] = mapped_column(String(16), nullable=False)

    ifc_value_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    value_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    value_number: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    value_boolean: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    unit: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
