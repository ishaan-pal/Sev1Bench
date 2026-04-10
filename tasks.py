"""Scenario definitions for Incident Response War Room."""

from __future__ import annotations

from pydantic import BaseModel, Field

from models import ServiceName, TaskDifficulty


class ScenarioConfig(BaseModel):
    task_id: str
    difficulty: TaskDifficulty
    title: str
    objective: str
    description: str
    hidden_root_cause: str
    max_steps: int
    seed: int
    optimal_steps: int
    initial_instances: dict[ServiceName, int]
    initial_metrics: dict[ServiceName, dict[str, float]]
    degrade_per_step: dict[ServiceName, dict[str, float]]
    log_hints: dict[ServiceName, list[str]]
    service_owners: dict[ServiceName, str]
    service_dependencies: dict[ServiceName, list[ServiceName]]
    last_deploy_minutes_ago: dict[ServiceName, int]
    recent_changes: list[str]
    customer_symptoms: list[str]
    topology_summary: str
    noise: dict[str, float] = Field(default_factory=lambda: {"cpu": 3.0, "latency_ms": 30.0, "error_rate": 0.01})


SCENARIOS: dict[str, ScenarioConfig] = {
    "easy_cpu_overload": ScenarioConfig(
        task_id="easy_cpu_overload",
        difficulty=TaskDifficulty.EASY,
        title="Easy: API CPU overload",
        objective="Restore the system to healthy status by reducing API overload before customer-facing latency spikes further.",
        description=(
            "Traffic surged on the API tier after a partner batch job started early. "
            "The correct fix is obvious from metrics."
        ),
        hidden_root_cause="API traffic surge saturated the API workers; scaling the API tier is the fastest safe fix.",
        max_steps=6,
        seed=101,
        optimal_steps=2,
        initial_instances={ServiceName.API: 2, ServiceName.DATABASE: 2},
        initial_metrics={
            ServiceName.API: {"cpu": 94.0, "latency_ms": 520.0, "error_rate": 0.09},
            ServiceName.DATABASE: {"cpu": 42.0, "latency_ms": 38.0, "error_rate": 0.01},
        },
        degrade_per_step={
            ServiceName.API: {"cpu": 2.5, "latency_ms": 65.0, "error_rate": 0.015},
            ServiceName.DATABASE: {"cpu": 1.0, "latency_ms": 4.0, "error_rate": 0.002},
        },
        log_hints={
            ServiceName.API: [
                "WARN api autoscaler disabled during maintenance window",
                "WARN request queue depth exceeded 1200",
                "INFO cpu throttling observed on worker pool",
            ],
            ServiceName.DATABASE: [
                "INFO replication healthy",
                "INFO query latency within SLO baseline",
            ],
        },
        service_owners={ServiceName.API: "traffic-platform", ServiceName.DATABASE: "data-infra"},
        service_dependencies={ServiceName.API: [ServiceName.DATABASE], ServiceName.DATABASE: []},
        last_deploy_minutes_ago={ServiceName.API: 19, ServiceName.DATABASE: 320},
        recent_changes=[
            "Traffic partner replay job started 15 minutes ahead of schedule.",
            "API autoscaler was paused for a maintenance rollback window.",
        ],
        customer_symptoms=[
            "Checkout API latency is above page threshold.",
            "5xx rate rising on partner-facing endpoints.",
        ],
        topology_summary="External traffic hits the API tier first; API requests depend on the primary database for reads and writes.",
    ),
    "medium_hidden_db_leak": ScenarioConfig(
        task_id="medium_hidden_db_leak",
        difficulty=TaskDifficulty.MEDIUM,
        title="Medium: Hidden database connection leak",
        objective="Identify the latent database issue and restore healthy request handling with the least disruptive action.",
        description=(
            "Customer errors are rising, but infrastructure metrics alone are ambiguous. "
            "Logs are needed to reveal the root cause."
        ),
        hidden_root_cause="A database connection leak exhausted the connection pool; restarting the database clears the pool and restores service.",
        max_steps=7,
        seed=202,
        optimal_steps=3,
        initial_instances={ServiceName.API: 3, ServiceName.DATABASE: 2},
        initial_metrics={
            ServiceName.API: {"cpu": 61.0, "latency_ms": 610.0, "error_rate": 0.13},
            ServiceName.DATABASE: {"cpu": 58.0, "latency_ms": 210.0, "error_rate": 0.06},
        },
        degrade_per_step={
            ServiceName.API: {"cpu": 1.0, "latency_ms": 85.0, "error_rate": 0.018},
            ServiceName.DATABASE: {"cpu": 1.8, "latency_ms": 35.0, "error_rate": 0.012},
        },
        log_hints={
            ServiceName.API: [
                "ERROR upstream timeout waiting for database checkout",
                "WARN retry budget exhausted for GET /accounts",
                "INFO api pods healthy but blocked on dependency",
            ],
            ServiceName.DATABASE: [
                "ERROR connection pool exhausted: 512 clients in use",
                "WARN idle connections not returned by inventory-worker",
                "INFO restart would recycle leaked sessions",
            ],
        },
        service_owners={ServiceName.API: "accounts-api", ServiceName.DATABASE: "data-infra"},
        service_dependencies={ServiceName.API: [ServiceName.DATABASE], ServiceName.DATABASE: []},
        last_deploy_minutes_ago={ServiceName.API: 47, ServiceName.DATABASE: 1440},
        recent_changes=[
            "Inventory worker deploy went out 42 minutes ago with a new connection pooling library.",
            "No infrastructure scaling or failover events were recorded.",
        ],
        customer_symptoms=[
            "Account lookups intermittently fail after retries.",
            "API pods appear healthy but customer latency keeps climbing.",
        ],
        topology_summary="API pods serve requests synchronously from the database and share a finite database connection pool.",
    ),
    "hard_cascading_failure": ScenarioConfig(
        task_id="hard_cascading_failure",
        difficulty=TaskDifficulty.HARD,
        title="Hard: Cascading failure across database and API",
        objective="Stop the cascade by stabilizing the database first, then restoring API capacity before the incident window expires.",
        description=(
            "A deep database issue is causing API worker exhaustion and customer-visible errors. "
            "This task requires multi-step reasoning and coordinated remediation."
        ),
        hidden_root_cause="Database lock contention triggered API worker starvation; restart the database first, then scale the API tier to clear the backlog.",
        max_steps=8,
        seed=303,
        optimal_steps=4,
        initial_instances={ServiceName.API: 2, ServiceName.DATABASE: 2},
        initial_metrics={
            ServiceName.API: {"cpu": 88.0, "latency_ms": 760.0, "error_rate": 0.19},
            ServiceName.DATABASE: {"cpu": 79.0, "latency_ms": 420.0, "error_rate": 0.11},
        },
        degrade_per_step={
            ServiceName.API: {"cpu": 2.0, "latency_ms": 95.0, "error_rate": 0.02},
            ServiceName.DATABASE: {"cpu": 2.2, "latency_ms": 55.0, "error_rate": 0.015},
        },
        log_hints={
            ServiceName.API: [
                "ERROR worker pool saturation due to upstream backlog",
                "WARN queue drain stalled waiting on database locks",
                "INFO scaling api after db recovery will flush backlog",
            ],
            ServiceName.DATABASE: [
                "ERROR lock wait timeout exceeded on orders shard",
                "WARN replication lag climbing after lock storm",
                "INFO restart clears lock queue and unblocks writers",
            ],
        },
        service_owners={ServiceName.API: "orders-api", ServiceName.DATABASE: "payments-data"},
        service_dependencies={ServiceName.API: [ServiceName.DATABASE], ServiceName.DATABASE: []},
        last_deploy_minutes_ago={ServiceName.API: 11, ServiceName.DATABASE: 180},
        recent_changes=[
            "Hot shard traffic increased after a flash sale started.",
            "A write-heavy feature flag was enabled on the orders path 9 minutes ago.",
        ],
        customer_symptoms=[
            "Order placement latency exceeds the paging SLO in all regions.",
            "Backlog continues to grow even after API retries.",
        ],
        topology_summary="Requests enter the API layer, enqueue work, and then block on database locks when the hot shard stalls.",
    ),
}


def list_task_ids() -> list[str]:
    return list(SCENARIOS.keys())
