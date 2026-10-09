from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PermissionLevel(IntEnum):
    READ = 1
    PREPARE = 2
    TRUSTED_EXECUTION = 3
    HIGH_IMPACT = 4


class RunStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    WAITING_FOR_HUMAN_VERIFICATION = "WAITING_FOR_HUMAN_VERIFICATION"
    BLOCKED = "BLOCKED"
    NEEDS_CONFIGURATION = "NEEDS_CONFIGURATION"


class CommandRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AssistantChatRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_history_size(self) -> "AssistantChatRequest":
        if sum(len(message.content) for message in self.history) > 20000:
            raise ValueError("Conversation history exceeds 20,000 characters")
        return self


class PlanResponse(BaseModel):
    run_id: UUID
    agent: str
    permission_level: PermissionLevel
    status: RunStatus
    summary: str
    plan: list[str]
    approval_id: UUID | None = None


class ApprovalDecision(BaseModel):
    approved: bool
    note: str | None = Field(default=None, max_length=2000)


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    action_summary: str
    status: str
    decision_note: str | None
    created_at: datetime
    decided_at: datetime | None


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    goal: str
    agent: str
    permission_level: int
    status: str
    summary: str
    approval_id: UUID | None
    created_at: datetime


class MemoryCreate(BaseModel):
    category: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1, max_length=10000)


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category: str
    content: str
    approved: bool
    created_at: datetime
    approved_at: datetime | None


class CareerEducation(BaseModel):
    degree: str = Field(default="", max_length=240)
    college: str = Field(default="", max_length=240)
    university: str = Field(default="", max_length=240)
    graduation_year: str = Field(default="", max_length=20)
    relevant_coursework: list[str] = Field(default_factory=list, max_length=100)


class CareerTarget(BaseModel):
    primary_role: str = Field(default="", max_length=240)
    secondary_roles: list[str] = Field(default_factory=list, max_length=50)
    experience_level: str = Field(default="", max_length=100)
    preferred_industries: list[str] = Field(default_factory=list, max_length=50)
    preferred_locations: list[str] = Field(default_factory=list, max_length=50)
    work_authorization_countries: list[str] = Field(default_factory=list, max_length=50)
    work_mode: str = Field(default="", max_length=80)
    salary_expectations: str = Field(default="", max_length=240)
    relocation_preference: str = Field(default="", max_length=100)
    notice_period: str = Field(default="", max_length=100)


class CareerProject(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=4000)
    purpose: str = Field(default="", max_length=2000)
    tools: list[str] = Field(default_factory=list, max_length=100)
    focus_areas: list[str] = Field(default_factory=list, max_length=100)
    datasets: list[str] = Field(default_factory=list, max_length=50)
    verified_metrics: list[str] = Field(default_factory=list, max_length=50)
    repository_url: str = Field(default="", max_length=2000)


class CareerProfile(BaseModel):
    name: str = Field(default="", max_length=240)
    email: str = Field(default="", max_length=320)
    phone: str = Field(default="", max_length=80)
    location: str = Field(default="", max_length=240)
    linkedin_url: str = Field(default="", max_length=2000)
    github_url: str = Field(default="", max_length=2000)
    portfolio_url: str = Field(default="", max_length=2000)
    professional_headline: str = Field(default="", max_length=500)
    education: CareerEducation = Field(default_factory=CareerEducation)
    career_target: CareerTarget = Field(default_factory=CareerTarget)
    skills: list[str] = Field(default_factory=list, max_length=300)
    projects: list[CareerProject] = Field(default_factory=list, max_length=100)


class MasterResumeCreate(BaseModel):
    content: str = Field(min_length=1, max_length=100000)
    change_note: str = Field(default="", max_length=500)


class MasterResumeVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content: str
    content_sha256: str
    change_note: str
    created_at: datetime


class MasterResumeVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content_sha256: str
    change_note: str
    created_at: datetime


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    due_at: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, pattern="^(pending|in_progress|done|blocked)$")
    due_at: datetime | None = None


class TaskResponse(BaseModel):
    id: UUID
    title: str
    description: str
    status: str
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LocalActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "list_files",
        "read_file",
        "create_file",
        "update_file",
        "delete_file",
        "launch_app",
        "run_command",
    ]
    path: str | None = Field(default=None, max_length=1000)
    content: str | None = Field(default=None, max_length=50000)
    app_name: Literal["notepad", "calculator", "explorer"] | None = None
    command: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_action_arguments(self) -> "LocalActionRequest":
        if self.action in {"read_file", "create_file", "update_file", "delete_file"} and not self.path:
            raise ValueError("File actions require a workspace-relative path")
        if self.action in {"create_file", "update_file"} and self.content is None:
            raise ValueError("File writes require content; use an empty string to write an empty file")
        if self.action == "launch_app" and self.app_name is None:
            raise ValueError("Launching an app requires an allow-listed app name")
        if self.action == "run_command" and not (self.command and self.command.strip()):
            raise ValueError("Running a command requires a non-empty command")
        return self


class LocalActionResponse(BaseModel):
    id: UUID
    action: str
    status: str
    summary: str
    result: dict | None = None
    approval_id: UUID | None = None
    confirmation: str | None = None


class AssistantChatResponse(BaseModel):
    status: RunStatus
    response: str
    action: LocalActionResponse | None = None
    job_search: dict | None = None


class AssistantStatusResponse(BaseModel):
    local_tools: str
    model_provider: str
    model_configured: bool
    model_reachable: bool
    model_name: str | None = None
    model_available: bool = False


class OllamaIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["action", "answer"]
    action: LocalActionRequest | None = None
    response: str | None = Field(default=None, max_length=8000)

    @model_validator(mode="after")
    def validate_decision_payload(self) -> "OllamaIntent":
        if self.decision == "action" and self.action is None:
            raise ValueError("An action decision must include a local action")
        if self.decision == "answer" and not self.response:
            raise ValueError("An answer decision must include a response")
        if self.decision == "answer" and self.action is not None:
            raise ValueError("An answer decision cannot include an action")
        return self
