"""Deterministic simulator backing the OpenEnv environment."""

from __future__ import annotations

import random
from copy import deepcopy
from typing import Any
from uuid import uuid4

from grader import grade_episode
from models import (
    ActionRecord,
    ActionType,
    Alert,
    AlertSeverity,
    IncidentAction,
    IncidentObservation,
    IncidentReward,
    IncidentState,
    MetricSnapshot,
    ServiceName,
    ServiceState,
)
from tasks import SCENARIOS, ScenarioConfig


class IncidentResponseSimulator:
    """Pure simulator with tuple-style step semantics."""

    def __init__(self, default_task_id: str = "easy_cpu_overload"):
        self.default_task_id = default_task_id
        self._rng = random.Random()
        self._scenario = SCENARIOS[default_task_id]
        self._state = self._build_state(self._scenario, seed=self._scenario.seed, episode_id=None)

    @property
    def state(self) -> IncidentState:
        return self._state.model_copy(deep=True)

    def reset(
        self,
        task_id: str | None = None,
        seed: int | None = None,
        episode_id: str | None = None,
    ) -> IncidentObservation:
        selected = SCENARIOS[task_id or self.default_task_id]
        chosen_seed = selected.seed if seed is None else seed
        self._scenario = selected
        self._state = self._build_state(selected, seed=chosen_seed, episode_id=episode_id)
        return self._build_observation(
            summary=(
                f"{selected.title}. Pager fired for elevated latency and error rate. "
                f"Customer symptoms: {'; '.join(selected.customer_symptoms)}. "
                "The system will continue degrading until the root cause is fixed."
            ),
            include_metrics=False,
            include_logs=False,
        )

    def step(
        self, action: IncidentAction
    ) -> tuple[IncidentObservation, IncidentReward, bool, dict[str, Any]]:
        previous_health = self._state.health_score
        self._state.step_count += 1

        action_penalty = self._validate_action(action)
        action_summary, operational_penalty = self._apply_action(action)
        self._apply_degradation()
        self._update_resolution_status()

        current_health = self._compute_health()
        time_penalty = round(0.8 + 0.25 * self._state.step_count, 3)
        health_delta = round((current_health - previous_health) / 12.0, 3)
        resolution_bonus = 4.0 if self._state.resolved else 0.0
        total_action_penalty = round(action_penalty + operational_penalty, 3)
        reward = IncidentReward(
            total=round(health_delta - time_penalty - total_action_penalty + resolution_bonus, 3),
            health_delta=health_delta,
            time_penalty=time_penalty,
            action_penalty=total_action_penalty,
            resolution_bonus=resolution_bonus,
        )
        self._state.health_score = current_health
        self._state.last_reward = reward

        done = self._state.resolved or self._state.step_count >= self._scenario.max_steps
        self._state.grader_score = grade_episode(self._state)

        observation = self._build_action_observation(action, action_summary, reward, done)
        self._state.history.append(
            ActionRecord(
                step=self._state.step_count,
                action=action,
                reward=reward,
                health_after=current_health,
                done=done,
                summary=observation.summary,
            )
        )
        self._state.grader_score = grade_episode(self._state)
        info = {
            "resolved": self._state.resolved,
            "health_score": self._state.health_score,
            "grader_score": self._state.grader_score,
            "root_cause_fixed": self._state.root_cause_fixed,
            "secondary_issue_fixed": self._state.secondary_issue_fixed,
        }
        return observation, reward, done, info

    def _build_state(
        self, scenario: ScenarioConfig, seed: int, episode_id: str | None
    ) -> IncidentState:
        self._rng = random.Random(seed)
        services: dict[ServiceName, ServiceState] = {}
        for service, metrics in scenario.initial_metrics.items():
            services[service] = ServiceState(
                service=service,
                instances=scenario.initial_instances[service],
                status="degraded",
                metrics=MetricSnapshot(**metrics),
                owner=scenario.service_owners[service],
                dependencies=scenario.service_dependencies[service],
                last_deploy_minutes_ago=scenario.last_deploy_minutes_ago[service],
                recent_logs=[],
            )

        state = IncidentState(
            episode_id=episode_id or str(uuid4()),
            step_count=0,
            task_id=scenario.task_id,
            difficulty=scenario.difficulty,
            objective=scenario.objective,
            max_steps=scenario.max_steps,
            services=services,
            hidden_root_cause=scenario.hidden_root_cause,
            health_score=0.0,
            notes={
                "seed": seed,
                "description": scenario.description,
                "recent_changes": scenario.recent_changes,
                "customer_symptoms": scenario.customer_symptoms,
                "topology_summary": scenario.topology_summary,
                "wrong_action_count": 0,
                "restart_count": 0,
                "scale_count": 0,
            },
        )
        self._refresh_operational_metrics(services)
        state.health_score = self._compute_health_for(services)
        return state

    def _validate_action(self, action: IncidentAction) -> float:
        if action.action_type in {ActionType.RESTART_SERVICE, ActionType.SCALE_SERVICE} and action.service is None:
            raise ValueError(f"{action.action_type.value} requires a service target")
        if action.action_type in {ActionType.CHECK_METRICS, ActionType.CHECK_LOGS, ActionType.DO_NOTHING} and action.service is not None:
            return 0.2
        return 0.0

    def _apply_action(self, action: IncidentAction) -> tuple[str, float]:
        scenario = self._scenario
        services = self._state.services

        if action.action_type == ActionType.CHECK_METRICS:
            return ("Pulled service metrics from dashboards with normal scrape lag.", 0.0)

        if action.action_type == ActionType.CHECK_LOGS:
            for service in services:
                services[service].recent_logs = self._generate_logs(service)
            return ("Collected logs from the incident window, including noisy platform chatter.", 0.0)

        if action.action_type == ActionType.DO_NOTHING:
            return ("No remediation was performed while error budgets continued to burn.", 0.1)

        assert action.service is not None
        target = services[action.service]
        self._state.notes["restart_count"] += int(action.action_type == ActionType.RESTART_SERVICE)
        self._state.notes["scale_count"] += int(action.action_type == ActionType.SCALE_SERVICE)

        if action.action_type == ActionType.RESTART_SERVICE:
            target.status = "recovering"
            target.metrics.cpu = max(20.0, target.metrics.cpu - 18.0)
            target.metrics.latency_ms = max(25.0, target.metrics.latency_ms - 180.0)
            target.metrics.error_rate = max(0.0, target.metrics.error_rate - 0.06)
            if self._state.task_id == "medium_hidden_db_leak" and action.service == ServiceName.DATABASE:
                self._state.root_cause_fixed = True
                return ("Restarted the database and recycled leaked connections.", 0.0)
            if self._state.task_id == "hard_cascading_failure" and action.service == ServiceName.DATABASE:
                self._state.root_cause_fixed = True
                return ("Restarted the database and cleared the lock storm.", 0.0)
            if self._state.task_id == "easy_cpu_overload" and action.service == ServiceName.API:
                self._state.notes["wrong_action_count"] += 1
                target.metrics.latency_ms += 120.0
                target.metrics.error_rate = min(1.0, target.metrics.error_rate + 0.03)
                return ("Restarted the API, causing a brief customer-visible flap while demand stayed high.", 0.6)
            if action.service == ServiceName.API and self._state.task_id != "easy_cpu_overload":
                self._state.notes["wrong_action_count"] += 1
                target.metrics.latency_ms += 90.0
                target.metrics.error_rate = min(1.0, target.metrics.error_rate + 0.02)
                return (
                    f"Restarted the {action.service.value} service, but it only added churn without removing the dependency bottleneck.",
                    0.45,
                )
            return (f"Restarted the {action.service.value} service.", 0.15)

        if action.action_type == ActionType.SCALE_SERVICE:
            target.instances += 1
            target.status = "recovering"
            target.metrics.cpu = max(15.0, target.metrics.cpu - 24.0)
            target.metrics.latency_ms = max(20.0, target.metrics.latency_ms - 220.0)
            target.metrics.error_rate = max(0.0, target.metrics.error_rate - 0.07)
            if self._state.task_id == "easy_cpu_overload" and action.service == ServiceName.API:
                self._state.root_cause_fixed = True
                return ("Scaled the API tier and relieved worker saturation.", 0.0)
            if self._state.task_id == "hard_cascading_failure" and action.service == ServiceName.API and self._state.root_cause_fixed:
                self._state.secondary_issue_fixed = True
                return ("Scaled the API tier and started draining the backlog after database recovery.", 0.0)
            if self._state.task_id == "hard_cascading_failure" and action.service == ServiceName.API:
                self._state.notes["wrong_action_count"] += 1
                return ("Scaled the API, but upstream database contention kept the queue pinned and increased operating cost.", 0.35)
            if action.service == ServiceName.DATABASE:
                self._state.notes["wrong_action_count"] += 1
                target.metrics.connection_utilization = min(1.0, target.metrics.connection_utilization + 0.08)
                return ("Scaled the database fleet, but the hot locks and leaked sessions remained on the same unhealthy path.", 0.3)
            return (f"Scaled the {action.service.value} service.", 0.1)

        raise ValueError(f"Unsupported action: {action.action_type}")

    def _apply_degradation(self) -> None:
        scenario = self._scenario
        for service_name, service in self._state.services.items():
            deltas = scenario.degrade_per_step[service_name].copy()
            if self._state.task_id == "easy_cpu_overload" and self._state.root_cause_fixed and service_name == ServiceName.API:
                deltas = {"cpu": -6.0, "latency_ms": -120.0, "error_rate": -0.03}
            elif self._state.task_id == "medium_hidden_db_leak" and self._state.root_cause_fixed:
                deltas = {"cpu": -4.0, "latency_ms": -110.0, "error_rate": -0.03}
            elif self._state.task_id == "hard_cascading_failure":
                if self._state.root_cause_fixed and service_name == ServiceName.DATABASE:
                    deltas = {"cpu": -8.0, "latency_ms": -140.0, "error_rate": -0.04}
                if self._state.root_cause_fixed and not self._state.secondary_issue_fixed and service_name == ServiceName.API:
                    deltas = {"cpu": -1.0, "latency_ms": -45.0, "error_rate": -0.01}
                if self._state.secondary_issue_fixed and service_name == ServiceName.API:
                    deltas = {"cpu": -9.0, "latency_ms": -170.0, "error_rate": -0.05}

            service.metrics.cpu = min(100.0, max(5.0, service.metrics.cpu + deltas["cpu"]))
            service.metrics.latency_ms = max(10.0, service.metrics.latency_ms + deltas["latency_ms"])
            service.metrics.error_rate = min(1.0, max(0.0, service.metrics.error_rate + deltas["error_rate"]))

            if service.metrics.cpu >= 85 or service.metrics.latency_ms >= 500 or service.metrics.error_rate >= 0.12:
                service.status = "overloaded"
            elif service.metrics.cpu >= 65 or service.metrics.latency_ms >= 180 or service.metrics.error_rate >= 0.04:
                service.status = "degraded"
            else:
                service.status = "healthy"
        self._refresh_operational_metrics(self._state.services)

    def _update_resolution_status(self) -> None:
        health = self._compute_health()
        if self._state.task_id == "easy_cpu_overload":
            self._state.resolved = self._state.root_cause_fixed and health >= 80.0
        elif self._state.task_id == "medium_hidden_db_leak":
            self._state.resolved = self._state.root_cause_fixed and health >= 82.0
        else:
            self._state.resolved = (
                self._state.root_cause_fixed
                and self._state.secondary_issue_fixed
                and health >= 84.0
            )

    def _build_observation(
        self,
        summary: str,
        include_metrics: bool,
        include_logs: bool,
        reward: IncidentReward | None = None,
        done: bool = False,
    ) -> IncidentObservation:
        visible_metrics: dict[ServiceName, MetricSnapshot] = {}
        visible_logs: dict[ServiceName, list[str]] = {}

        if include_metrics:
            for service_name, service in self._state.services.items():
                visible_metrics[service_name] = self._noisy_metrics(service.metrics)

        if include_logs:
            for service_name, service in self._state.services.items():
                lines = service.recent_logs or ["INFO no immediately actionable lines in the latest sample"]
                visible_logs[service_name] = lines[:]

        metadata = {
            "step_count": self._state.step_count,
            "health_score": self._compute_health(),
            "reward_breakdown": reward.model_dump() if reward else None,
            "task_description": self._state.notes["description"],
            "customer_symptoms": self._state.notes["customer_symptoms"],
        }
        return IncidentObservation(
            task_id=self._state.task_id,
            difficulty=self._state.difficulty,
            objective=self._state.objective,
            topology_summary=self._state.notes["topology_summary"],
            recent_changes=list(self._state.notes["recent_changes"]),
            visible_metrics=visible_metrics,
            visible_logs=visible_logs,
            alerts=self._build_alerts(),
            summary=summary,
            available_actions=[action.value for action in ActionType],
            done=done,
            reward=None if reward is None else reward.total,
            metadata=metadata,
        )

    def _build_action_observation(
        self,
        action: IncidentAction,
        action_summary: str,
        reward: IncidentReward,
        done: bool,
    ) -> IncidentObservation:
        include_metrics = action.action_type == ActionType.CHECK_METRICS
        include_logs = action.action_type == ActionType.CHECK_LOGS
        health = self._compute_health()
        summary = (
            f"{action_summary} Current system health is {health:.1f}/100. "
            f"{'Incident resolved.' if done and self._state.resolved else 'Incident still active.'}"
        )
        return self._build_observation(
            summary=summary,
            include_metrics=include_metrics,
            include_logs=include_logs,
            reward=reward,
            done=done,
        )

    def _build_alerts(self) -> list[Alert]:
        alerts: list[Alert] = []
        for service_name, service in self._state.services.items():
            if service.metrics.error_rate >= 0.12 or service.metrics.latency_ms >= 600:
                severity = AlertSeverity.CRITICAL
            elif service.metrics.error_rate >= 0.04 or service.metrics.latency_ms >= 180 or service.metrics.cpu >= 75:
                severity = AlertSeverity.WARNING
            else:
                severity = AlertSeverity.INFO
            message = (
                f"{service_name.value} cpu={service.metrics.cpu:.0f}% "
                f"latency={service.metrics.latency_ms:.0f}ms "
                f"errors={service.metrics.error_rate:.2%} "
                f"queue={service.metrics.queue_depth} "
                f"conn={service.metrics.connection_utilization:.0%}"
            )
            alerts.append(Alert(service=service_name, severity=severity, message=message))
        return alerts

    def _noisy_metrics(self, metrics: MetricSnapshot) -> MetricSnapshot:
        noise = self._scenario.noise
        return MetricSnapshot(
            cpu=min(100.0, max(0.0, metrics.cpu + self._rng.uniform(-noise["cpu"], noise["cpu"]))),
            latency_ms=max(0.0, metrics.latency_ms + self._rng.uniform(-noise["latency_ms"], noise["latency_ms"])),
            error_rate=min(1.0, max(0.0, metrics.error_rate + self._rng.uniform(-noise["error_rate"], noise["error_rate"]))),
            traffic_rps=max(0.0, metrics.traffic_rps + self._rng.uniform(-15.0, 15.0)),
            queue_depth=max(0, int(metrics.queue_depth + self._rng.uniform(-20.0, 20.0))),
            connection_utilization=min(1.0, max(0.0, metrics.connection_utilization + self._rng.uniform(-0.03, 0.03))),
        )

    def _compute_health(self) -> float:
        return self._compute_health_for(self._state.services)

    def _compute_health_for(self, services: dict[ServiceName, ServiceState]) -> float:
        total = 0.0
        for service in services.values():
            cpu_score = max(0.0, 100.0 - abs(service.metrics.cpu - 45.0) * 1.1)
            latency_score = max(0.0, 100.0 - service.metrics.latency_ms / 8.0)
            error_score = max(0.0, 100.0 - service.metrics.error_rate * 600.0)
            queue_score = max(0.0, 100.0 - service.metrics.queue_depth / 12.0)
            connection_score = max(0.0, 100.0 - service.metrics.connection_utilization * 100.0)
            service_health = (
                0.2 * cpu_score
                + 0.25 * latency_score
                + 0.25 * error_score
                + 0.15 * queue_score
                + 0.15 * connection_score
            )
            total += service_health
        return round(total / len(services), 2)

    def _refresh_operational_metrics(self, services: dict[ServiceName, ServiceState]) -> None:
        api = services[ServiceName.API]
        database = services[ServiceName.DATABASE]

        database.metrics.connection_utilization = min(
            1.0,
            max(0.08, 0.2 + database.metrics.cpu / 100.0 * 0.5 + database.metrics.error_rate * 1.8),
        )
        database.metrics.traffic_rps = max(80.0, round((280.0 + api.metrics.cpu * 11.0) * 0.72, 1))
        database.metrics.queue_depth = max(
            0,
            int(database.metrics.latency_ms * 1.1 + database.metrics.error_rate * 2200),
        )

        api.metrics.traffic_rps = max(120.0, round(280.0 + api.metrics.cpu * 11.0 - api.instances * 30.0, 1))
        api.metrics.queue_depth = max(
            0,
            int(api.metrics.latency_ms * 1.7 + api.metrics.error_rate * 2500 - api.instances * 90),
        )
        api.metrics.connection_utilization = min(
            1.0,
            max(0.05, database.metrics.connection_utilization * 0.85 + api.metrics.error_rate * 0.35),
        )

    def _generate_logs(self, service: ServiceName) -> list[str]:
        scenario = self._scenario
        service_state = self._state.services[service]
        generic_noise = [
            f"INFO owner={service_state.owner} deploy_age_min={service_state.last_deploy_minutes_ago}",
            f"INFO status={service_state.status} instances={service_state.instances}",
            "DEBUG healthcheck jitter observed during log sampling",
        ]
        context_line = f"INFO recent_change={scenario.recent_changes[0]}"
        metrics_line = (
            f"INFO cpu={service_state.metrics.cpu:.0f}% latency={service_state.metrics.latency_ms:.0f}ms "
            f"queue={service_state.metrics.queue_depth} conn={service_state.metrics.connection_utilization:.0%}"
        )
        return deepcopy(scenario.log_hints[service]) + [context_line, metrics_line] + generic_noise
