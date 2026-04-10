"""OpenEnv server wrapper for Incident Response War Room."""

from __future__ import annotations

from typing import Any

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import EnvironmentMetadata

from models import (
    IncidentAction,
    IncidentObservation,
    IncidentState,
)
from simulator import IncidentResponseSimulator


class IncidentResponseEnvironment(
    Environment[IncidentAction, IncidentObservation, IncidentState]
):
    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self):
        super().__init__()
        self._simulator = IncidentResponseSimulator()

    def reset(
        self,
        seed: int | None = None,
        episode_id: str | None = None,
        **kwargs: Any,
    ) -> IncidentObservation:
        task_id = kwargs.get("task_id")
        return self._simulator.reset(task_id=task_id, seed=seed, episode_id=episode_id)

    def step(
        self,
        action: IncidentAction,
        timeout_s: float | None = None,
        **kwargs: Any,
    ) -> IncidentObservation:
        del timeout_s, kwargs
        observation, reward, done, info = self._simulator.step(action)
        observation.reward = reward.total
        observation.done = done
        observation.metadata["info"] = info
        return observation

    @property
    def state(self) -> IncidentState:
        return self._simulator.state

    def get_metadata(self) -> EnvironmentMetadata:
        return EnvironmentMetadata(
            name="Incident Response War Room",
            description="Distributed-system outage simulation for on-call diagnosis and remediation.",
            version="0.1.0",
            author="OpenEnv competition scaffold",
        )
