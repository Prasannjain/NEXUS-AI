"""Pydantic request/response models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

WORKFLOW_CATEGORIES = ["employee_onboarding", "invoice_processing", "customer_request"]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=4, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    user: "UserOut"


class RoleOut(BaseModel):
    name: str
    description: str = ""
    permissions: list[str] = []


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    department: str = ""
    role: RoleOut

    model_config = {"from_attributes": True}


class WorkflowCreateRequest(BaseModel):
    request_text: str = Field(min_length=8, max_length=4000)
    category: Literal["auto", "employee_onboarding", "invoice_processing", "customer_request"] | None = "auto"

    @field_validator("category", mode="before")
    @classmethod
    def _normalise(cls, value: Any):
        if value in ("", "auto", None):
            return "auto"
        return value


class PlanPreviewRequest(BaseModel):
    request_text: str = Field(min_length=8, max_length=4000)
    category: str | None = None


class TaskOut(BaseModel):
    task_id: str
    seq: int
    description: str
    agent_name: str
    tool_name: str
    arguments: dict[str, Any] = {}
    depends_on: list[str] = []
    requires_approval: bool
    risk_level: str
    status: str
    output_summary: str = ""
    error: str = ""
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


class ApprovalOut(BaseModel):
    id: str
    workflow_id: str
    task_id: str
    agent_name: str
    action: str
    details: dict[str, Any] = {}
    risk_level: str
    policy_reason: str
    status: str
    requested_at: datetime
    decided_at: datetime | None = None
    decided_by: str = ""
    comment: str = ""

    model_config = {"from_attributes": True}


class ApprovalDecisionRequest(BaseModel):
    action: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=2000)


class WorkflowOut(BaseModel):
    id: str
    title: str
    request_text: str
    category: str
    status: str
    current_stage: str
    active_agent: str
    progress: float
    requester: str = ""
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    result_summary: str = ""
    error_message: str = ""
    pending_approvals: int = 0
    task_counts: dict[str, int] = {}
    llm_provider: str = ""

    model_config = {"from_attributes": True}


class WorkflowDetailOut(WorkflowOut):
    plan: dict[str, Any] | None = None
    tasks: list[TaskOut] = []
    approvals: list[ApprovalOut] = []
    executions: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    checkpoint: dict[str, Any] = {}
    final_report: dict[str, Any] | None = None


class ToolRegisterRequest(BaseModel):
    name: str = Field(min_length=3, max_length=120, pattern=r"^[a-z0-9_.\-]+$")
    display_name: str = Field(min_length=2, max_length=120)
    description: str = ""
    integration_key: str
    required_permission: str = "tools.execute"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    side_effect: Literal["read", "write", "financial"] = "read"
    requires_approval: bool = False
    retry_safe: bool = True
    reversible: bool = True
    agent_scope: list[str] = Field(default_factory=list)


class ToolUpdateRequest(BaseModel):
    enabled: bool | None = None
    required_permission: str | None = None
    agent_scope: list[str] | None = None
    risk_level: Literal["low", "medium", "high", "critical"] | None = None
    requires_approval: bool | None = None


class IntegrationUpdateRequest(BaseModel):
    connection_status: Literal["connected", "degraded", "disabled"]
    config: dict[str, Any] | None = None


TokenResponse.model_rebuild()
