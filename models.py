"""Typed models for the Incident Response War Room environment."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BaseAction(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )

    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseObservation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )

    done: bool = False
    reward: bool | int | float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseState(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )

    episode_id: str | None = None
    step_count: int = Field(default=0, ge=0)


class ServiceName(str, Enum):
    API = "api"
    DATABASE = "database"


class ActionType(str, Enum):
    CHECK_METRICS = "check_metrics"
    CHECK_LOGS = "check_logs"
    RESTART_SERVICE = "restart_service"
    SCALE_SERVICE = "scale_service"
    DO_NOTHING = "do_nothing"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class TaskDifficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class MetricSnapshot(BaseModel):
    cpu: float = Field(..., ge=0.0, le=100.0)
    latency_ms: float = Field(..., ge=0.0)
    error_rate: float = Field(..., ge=0.0, le=1.0)
    traffic_rps: float = Field(default=0.0, ge=0.0)
    queue_depth: int = Field(default=0, ge=0)
    connection_utilization: float = Field(default=0.0, ge=0.0, le=1.0)


class Alert(BaseModel):
    service: ServiceName
    severity: AlertSeverity
    message: str


class ServiceState(BaseModel):
    service: ServiceName
    instances: int = Field(..., ge=1)
    status: Literal["healthy", "degraded", "recovering", "overloaded"]
    metrics: MetricSnapshot
    owner: str = ""
    dependencies: list[ServiceName] = Field(default_factory=list)
    last_deploy_minutes_ago: int = Field(default=0, ge=0)
    recent_logs: list[str] = Field(default_factory=list)


class IncidentAction(BaseAction):
    action_type: ActionType
    service: ServiceName | None = None


class IncidentReward(BaseModel):
    total: float
    health_delta: float
    time_penalty: float
    action_penalty: float
    resolution_bonus: float


class IncidentObservation(BaseObservation):
    task_id: str
    difficulty: TaskDifficulty
    objective: str
    topology_summary: str = ""
    recent_changes: list[str] = Field(default_factory=list)
    visible_metrics: dict[ServiceName, MetricSnapshot] = Field(default_factory=dict)
    visible_logs: dict[ServiceName, list[str]] = Field(default_factory=dict)
    alerts: list[Alert] = Field(default_factory=list)
    summary: str = ""
    available_actions: list[str] = Field(default_factory=list)


class ActionRecord(BaseModel):
    step: int
    action: IncidentAction
    reward: IncidentReward
    health_after: float
    done: bool
    summary: str


class IncidentState(BaseState):
    task_id: str
    difficulty: TaskDifficulty
    objective: str
    max_steps: int
    services: dict[ServiceName, ServiceState]
    hidden_root_cause: str
    root_cause_fixed: bool = False
    secondary_issue_fixed: bool = False
    resolved: bool = False
    health_score: float = Field(..., ge=0.0, le=100.0)
    grader_score: float = Field(default=0.0, ge=0.0, le=1.0)
    last_reward: IncidentReward | None = None
    history: list[ActionRecord] = Field(default_factory=list)
    notes: dict[str, Any] = Field(default_factory=dict)
