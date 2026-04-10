"""FastAPI application for Incident Response War Room."""

from __future__ import annotations

from openenv.core.env_server.http_server import create_app

from models import IncidentAction, IncidentObservation

from .incident_response_environment import IncidentResponseEnvironment


app = create_app(
    IncidentResponseEnvironment,
    IncidentAction,
    IncidentObservation,
    env_name="incident_response_war_room",
    max_concurrent_envs=4,
)


def main(host: str = "0.0.0.0", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
