"""OpenEnv client for the Incident Response War Room environment."""

from __future__ import annotations

import os
import threading
from typing import Any

from openai import OpenAI
from openenv.core import EnvClient
from openenv.core.client_types import StepResult

from models import (
    Alert,
    IncidentAction,
    IncidentObservation,
    IncidentState,
    MetricSnapshot,
    ServiceName,
    ServiceState,
    TaskDifficulty,
)

_PROXY_PROBE_LOCK = threading.Lock()
_PROXY_PROBE_ATTEMPTED = False


def get_llm_client(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> OpenAI:
    try:
        resolved_api_key = api_key if api_key is not None else os.environ["HF_TOKEN"]
        resolved_base_url = (
            base_url if base_url is not None else os.environ["API_BASE_URL"]
        )
    except KeyError as exc:
        missing_name = exc.args[0]
        raise SystemExit(
            f"Remote inference requires {missing_name}. "
            "Use the injected LiteLLM proxy credentials or pass --no-openai."
        ) from exc

    return OpenAI(api_key=resolved_api_key, base_url=resolved_base_url)


def chat_completion(
    *,
    client: OpenAI,
    model: str,
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> Any:
    print("LLM CALL ROUTED THROUGH PROXY:", client.base_url, flush=True)
    return client.chat.completions.create(
        model=model,
        messages=messages,
        **kwargs,
    )


def ensure_proxy_probe(model_name: str | None = None) -> bool:
    global _PROXY_PROBE_ATTEMPTED

    with _PROXY_PROBE_LOCK:
        if _PROXY_PROBE_ATTEMPTED:
            return False
        _PROXY_PROBE_ATTEMPTED = True

    if "HF_TOKEN" not in os.environ or "API_BASE_URL" not in os.environ:
        return False

    try:
        client = get_llm_client()
        chat_completion(
            client=client,
            model=model_name or os.getenv("MODEL_NAME", "openai/gpt-4.1-mini"),
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            temperature=0,
        )
        return True
    except Exception:
        return False


class IncidentResponseWarRoomEnv(
    EnvClient[IncidentAction, IncidentObservation, IncidentState]
):
    """Client for the Incident Response War Room environment."""

    def _step_payload(self, action: IncidentAction) -> dict[str, Any]:
        return action.model_dump(mode="json")

    def _parse_result(self, payload: dict[str, Any]) -> StepResult[IncidentObservation]:
        obs_data = payload.get("observation", {})
        observation = IncidentObservation(
            task_id=obs_data.get("task_id", ""),
            difficulty=TaskDifficulty(obs_data.get("difficulty", "easy")),
            objective=obs_data.get("objective", ""),
            topology_summary=obs_data.get("topology_summary", ""),
            recent_changes=list(obs_data.get("recent_changes", [])),
            visible_metrics={
                ServiceName(name): MetricSnapshot(**metrics)
                for name, metrics in obs_data.get("visible_metrics", {}).items()
            },
            visible_logs={
                ServiceName(name): list(lines)
                for name, lines in obs_data.get("visible_logs", {}).items()
            },
            alerts=[Alert(**item) for item in obs_data.get("alerts", [])],
            summary=obs_data.get("summary", ""),
            available_actions=list(obs_data.get("available_actions", [])),
            done=payload.get("done", False),
            reward=payload.get("reward"),
            metadata=obs_data.get("metadata", {}),
        )
        return StepResult(
            observation=observation,
            reward=payload.get("reward"),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: dict[str, Any]) -> IncidentState:
        services = {
            ServiceName(name): ServiceState(
                service=ServiceName(name),
                instances=value["instances"],
                status=value["status"],
                metrics=MetricSnapshot(**value["metrics"]),
                recent_logs=value.get("recent_logs", []),
            )
            for name, value in payload.get("services", {}).items()
        }
        return IncidentState(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
            task_id=payload.get("task_id", ""),
            difficulty=TaskDifficulty(payload.get("difficulty", "easy")),
            objective=payload.get("objective", ""),
            max_steps=payload.get("max_steps", 0),
            services=services,
            hidden_root_cause=payload.get("hidden_root_cause", ""),
            root_cause_fixed=payload.get("root_cause_fixed", False),
            secondary_issue_fixed=payload.get("secondary_issue_fixed", False),
            resolved=payload.get("resolved", False),
            health_score=payload.get("health_score", 0.0),
            grader_score=payload.get("grader_score", 0.0),
            last_reward=payload.get("last_reward"),
            history=payload.get("history", []),
            notes=payload.get("notes", {}),
        )