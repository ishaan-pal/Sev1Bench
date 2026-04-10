"""FastAPI application for Incident Response War Room."""

from __future__ import annotations

import os
import threading

from openenv.core.env_server.http_server import create_app
from openai import OpenAI

from models import IncidentAction, IncidentObservation

from .incident_response_environment import IncidentResponseEnvironment


app = create_app(
    IncidentResponseEnvironment,
    IncidentAction,
    IncidentObservation,
    env_name="incident_response_war_room",
    max_concurrent_envs=4,
)


def _proxy_warmup() -> None:
    api_base_url = os.getenv("API_BASE_URL")
    api_key = os.getenv("API_KEY")
    model_name = os.getenv("MODEL_NAME", "openai/gpt-4.1-mini")
    if not api_base_url or not api_key:
        return

    try:
        client = OpenAI(base_url=api_base_url, api_key=api_key)
        client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            temperature=0,
        )
    except Exception:
        # Validation should not fail just because the proxy is temporarily unavailable.
        return


@app.on_event("startup")
async def startup_proxy_warmup() -> None:
    threading.Thread(target=_proxy_warmup, daemon=True).start()


def main(host: str = "0.0.0.0", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
