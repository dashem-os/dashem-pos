import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, JSON, String
from sqlmodel import Field, SQLModel, UniqueConstraint


class AgentRunStatusEnum(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class ToolCallStatusEnum(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DENIED = "DENIED"


class ApprovalStatusEnum(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CANCELED = "CANCELED"


class ContextEdge(SQLModel, table=True):
    __tablename__ = "context_edges"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_type",
            "source_id",
            "relation",
            "target_type",
            "target_id",
            name="uq_tenant_context_edge",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: Optional[uuid.UUID] = Field(default=None, foreign_key="stores.id", index=True)
    source_type: str = Field(index=True)
    source_id: str = Field(index=True)
    relation: str = Field(index=True)
    target_type: str = Field(index=True)
    target_id: str = Field(index=True)
    provenance: str = Field(index=True)
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    occurred_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class AgentRun(SQLModel, table=True):
    __tablename__ = "agent_runs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: Optional[uuid.UUID] = Field(default=None, foreign_key="stores.id", index=True)
    actor_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    agent_key: str = Field(index=True)
    status: AgentRunStatusEnum = Field(
        default=AgentRunStatusEnum.PENDING,
        sa_column=Column(String, nullable=False, index=True),
    )
    model: Optional[str] = Field(default=None, index=True)
    model_version: Optional[str] = None
    input_context: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    output: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    correlation_id: Optional[str] = Field(default=None, index=True)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class AgentToolCall(SQLModel, table=True):
    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        UniqueConstraint("agent_run_id", "idempotency_key", name="uq_agent_run_tool_idempotency"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: Optional[uuid.UUID] = Field(default=None, foreign_key="stores.id", index=True)
    agent_run_id: uuid.UUID = Field(foreign_key="agent_runs.id", index=True)
    tool_key: str = Field(index=True)
    status: ToolCallStatusEnum = Field(
        default=ToolCallStatusEnum.REQUESTED,
        sa_column=Column(String, nullable=False, index=True),
    )
    idempotency_key: str = Field(index=True)
    arguments: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    result: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    error: Optional[str] = None
    requested_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    completed_at: Optional[datetime] = None


class ApprovalRequest(SQLModel, table=True):
    __tablename__ = "approval_requests"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: Optional[uuid.UUID] = Field(default=None, foreign_key="stores.id", index=True)
    agent_run_id: Optional[uuid.UUID] = Field(default=None, foreign_key="agent_runs.id", index=True)
    tool_call_id: Optional[uuid.UUID] = Field(default=None, foreign_key="agent_tool_calls.id", index=True)
    requested_by_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    decided_by_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", index=True)
    action: str = Field(index=True)
    reason: str
    status: ApprovalStatusEnum = Field(
        default=ApprovalStatusEnum.PENDING,
        sa_column=Column(String, nullable=False, index=True),
    )
    expires_at: Optional[datetime] = Field(default=None, index=True)
    decided_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
