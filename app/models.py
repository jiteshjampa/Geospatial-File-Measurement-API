from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    feature_count: Mapped[int] = mapped_column(Integer, nullable=False)
    crs: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="COMPLETED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    features: Mapped[list["MeasuredFeature"]] = relationship(
        back_populates="uploaded_file",
        cascade="all, delete-orphan",
        order_by="MeasuredFeature.feature_index",
    )


class MeasuredFeature(Base):
    __tablename__ = "measured_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(
        ForeignKey("uploaded_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feature_index: Mapped[int] = mapped_column(Integer, nullable=False)
    geometry_type: Mapped[str] = mapped_column(String(40), nullable=False)
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    geometry_crs: Mapped[str] = mapped_column(String(100), nullable=False, default="EPSG:4326")
    properties: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    measurement_status: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    uploaded_file: Mapped[UploadedFile] = relationship(back_populates="features")
