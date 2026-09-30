from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PermissionRule(Base):
    __tablename__ = "permission_rule"
    __table_args__ = (
        Index(
            "ix_permission_rule_lookup", "user_id", "bucket", "connector", "tool"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    bucket: Mapped[str] = mapped_column(String, nullable=False, index=True)
    connector: Mapped[str | None] = mapped_column(String, nullable=True)
    tool: Mapped[str | None] = mapped_column(String, nullable=True)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )