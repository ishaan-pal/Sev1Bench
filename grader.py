"""Deterministic grading logic for Incident Response War Room."""

from __future__ import annotations

from models import ActionType, IncidentState, ServiceName


def grade_episode(state: IncidentState) -> float:
    """Grade an episode deterministically on a 0.0 to 1.0 scale."""
    history = state.history
    steps = max(1, state.step_count)
    metrics_checked = any(item.action.action_type == ActionType.CHECK_METRICS for item in history)
    logs_checked = any(item.action.action_type == ActionType.CHECK_LOGS for item in history)
    restarted_db = any(
        item.action.action_type == ActionType.RESTART_SERVICE and item.action.service == ServiceName.DATABASE
        for item in history
    )
    scaled_api = any(
        item.action.action_type == ActionType.SCALE_SERVICE and item.action.service == ServiceName.API
        for item in history
    )
    wrong_action_count = int(state.notes.get("wrong_action_count", 0))

    health_component = state.health_score / 100.0
    resolution_component = 1.0 if state.resolved else 0.0
    efficiency_component = max(0.0, 1.0 - ((steps - 1) / max(1, state.max_steps - 1)))
    investigation_component = 0.0
    if metrics_checked:
        investigation_component += 0.1
    if logs_checked:
        investigation_component += 0.1

    if state.task_id == "easy_cpu_overload":
        remediation_component = 0.2 if scaled_api else 0.0
        score = 0.45 * resolution_component + 0.2 * health_component + 0.15 * efficiency_component + remediation_component + investigation_component
    elif state.task_id == "medium_hidden_db_leak":
        remediation_component = 0.15 if restarted_db else 0.0
        log_gate = 1.0 if logs_checked else 0.75
        score = (
            0.4 * resolution_component
            + 0.2 * health_component
            + 0.15 * efficiency_component
            + remediation_component
            + investigation_component
        ) * log_gate
    else:
        remediation_component = 0.1 * float(restarted_db) + 0.1 * float(scaled_api)
        ordered_fix = 0.1
        if restarted_db and scaled_api:
            db_step = next(
                item.step for item in history if item.action.action_type == ActionType.RESTART_SERVICE and item.action.service == ServiceName.DATABASE
            )
            api_step = next(
                item.step for item in history if item.action.action_type == ActionType.SCALE_SERVICE and item.action.service == ServiceName.API
            )
            ordered_fix = 0.1 if db_step < api_step else 0.03
        else:
            ordered_fix = 0.0
        score = (
            0.35 * resolution_component
            + 0.2 * health_component
            + 0.1 * efficiency_component
            + remediation_component
            + ordered_fix
            + investigation_component
        )

    score -= min(0.18, wrong_action_count * 0.06)
    return round(max(0.0, min(1.0, score)), 4)
