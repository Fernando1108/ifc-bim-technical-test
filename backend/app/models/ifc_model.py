from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
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


class IfcModel(Base):
    __tablename__ = "ifc_models"

    __table_args__ = (
        UniqueConstraint(
            "storage_path",
            name="uq_ifc_models_storage_path",
        ),
        CheckConstraint(
            "file_size_bytes > 0",
            name="ck_ifc_models_file_size_positive",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="ck_ifc_models_status",
        ),
        Index("ix_ifc_models_owner_id", "owner_id"),
        Index("ix_ifc_models_status", "status"),
        Index("ix_ifc_models_sha256", "sha256"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    owner_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)

    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )

    ifc_schema: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    processing_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
