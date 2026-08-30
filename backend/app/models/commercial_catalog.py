from datetime import datetime

from sqlalchemy import CheckConstraint, Column, Index, JSON, String, Text
from sqlmodel import Field, SQLModel


class CommercialActivity(SQLModel, table=True):
    """Owner-managed commercial activity used to compose an offer."""

    __tablename__ = "commercial_activities"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_commercial_activity_version_positive"),
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'RETIRED')",
            name="ck_commercial_activity_status",
        ),
    )

    key: str = Field(primary_key=True, max_length=80)
    name: str = Field(index=True, max_length=160)
    description: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(default="ACTIVE", sa_column=Column(String(24), nullable=False, index=True))
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CommercialActivityCapability(SQLModel, table=True):
    """Capability rule in an activity matrix; it does not grant tenant access."""

    __tablename__ = "commercial_activity_capabilities"
    __table_args__ = (
        CheckConstraint(
            "role IN ('REQUIRED', 'OPTIONAL')",
            name="ck_commercial_activity_capability_role",
        ),
        Index(
            "ix_commercial_activity_capabilities_capability_key",
            "capability_key",
        ),
    )

    activity_key: str = Field(
        foreign_key="commercial_activities.key", primary_key=True, max_length=80
    )
    capability_key: str = Field(
        foreign_key="capability_definitions.key", primary_key=True, max_length=80
    )
    role: str = Field(sa_column=Column(String(24), nullable=False))
    default_selected: bool = Field(default=False)
    configuration: dict = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict)
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
