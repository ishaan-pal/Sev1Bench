---
title: Incident Response War Room
emoji: 🚨
colorFrom: red
colorTo: gray
sdk: docker
pinned: false
app_port: 8000
base_path: /web
tags:
  - openenv
  - reliability
  - incident-response
---

# Incident Response War Room

Incident Response War Room is a production-style OpenEnv environment where an AI agent plays the on-call engineer during a distributed-system outage. The system contains an API tier and a database tier, exposes noisy metrics and logs, recent deploy/change context, service ownership, queue pressure, and connection saturation, degrades over time, and requires the agent to infer the root cause before taking remediation actions.

## What The Agent Must Do

The agent must:

- analyze partial and noisy observations
- prioritize metrics versus logs depending on the scenario
- choose remediations that improve system health quickly
- avoid destructive or irrelevant interventions

Available actions:

- `check_metrics`
- `check_logs`
- `restart_service(service)`
- `scale_service(service)`
- `do_nothing`

Services:

- `api`
- `database`

Metrics:

- `cpu`
- `latency_ms`
- `error_rate`

## Tasks

The environment ships with three reproducible tasks.

1. `easy_cpu_overload`
   Objective: detect obvious API overload and scale the API tier.
   Expected winning pattern: `check_metrics -> scale_service(api)`.

2. `medium_hidden_db_leak`
   Objective: use logs to discover the hidden database connection leak.
   Expected winning pattern: `check_metrics -> check_logs -> restart_service(database)`.

3. `hard_cascading_failure`
   Objective: stabilize the database first, then restore API capacity to clear the backlog.
   Expected winning pattern: `check_metrics -> check_logs -> restart_service(database) -> scale_service(api)`.

Each task is deterministic, seeded, and graded from `0.0` to `1.0`.

## Environment Design

The implementation uses two layers:

- `simulator.py`: deterministic simulator with `reset()`, tuple-style `step(action) -> (observation, reward, done, info)`, and full `state`
- `server/incident_response_environment.py`: OpenEnv wrapper for FastAPI and WebSocket serving

Observations are intentionally partial:

- `check_metrics` reveals noisy service metrics
- `check_logs` reveals clue-bearing logs mixed with deploy metadata and platform noise
- remediation actions return operational summaries and can create additional churn when they are the wrong fix

This is intended to feel like a real on-call debugging loop rather than a toy benchmark:

- each service has an owner, dependency graph, and recent deploy age
- task briefs include customer symptoms and recent infrastructure or product changes
- metrics include queue depth, traffic pressure, and connection utilization, not just CPU/latency/errors
- wrong interventions have realistic blast-radius costs instead of only abstract penalties

The hidden state contains the real root cause, remediation flags, full service metrics, history, and grader score.

## Reward Design

The reward is continuous and deterministic:

- positive reward from improvement in overall health score
- time penalty every step to create urgency
- action penalty for irrelevant or malformed actions
- resolution bonus when the incident is actually stabilized

The reward breakdown is returned as a typed `IncidentReward` model and serialized into observation metadata.

## Grading

`grader.py` computes the final score.

Scoring combines:

- resolution status
- final health score
- efficiency in steps taken
- evidence of correct investigation
- task-specific remediation correctness

The medium task caps scores if the agent skips logs. The hard task rewards doing the database restart before scaling the API tier.

## Project Layout

```text
__init__.py
client.py
grader.py
models.py
simulator.py
tasks.py
server/
  app.py
  incident_response_environment.py
inference.py
openenv.yaml
Dockerfile
```

## Local Development

Install dependencies and generate the lockfile:

```bash
uv sync
uv lock
```

Run the server locally:

```bash
uv run server
```

Validate the environment:

```bash
openenv validate
openenv validate --verbose
```

Validate the running server:

```bash
openenv validate --url http://localhost:8000
```

## Python Usage

Direct simulator usage:

```python
from models import ActionType, IncidentAction, ServiceName
from simulator import IncidentResponseSimulator

sim = IncidentResponseSimulator()
obs = sim.reset(task_id="hard_cascading_failure")
obs, reward, done, info = sim.step(IncidentAction(action_type=ActionType.CHECK_METRICS))
obs, reward, done, info = sim.step(
    IncidentAction(action_type=ActionType.CHECK_LOGS)
)
obs, reward, done, info = sim.step(
    IncidentAction(action_type=ActionType.RESTART_SERVICE, service=ServiceName.DATABASE)
)
```

Remote OpenEnv client usage:

```python
from client import IncidentResponseWarRoomEnv
from models import ActionType, IncidentAction

with IncidentResponseWarRoomEnv(base_url="http://localhost:8000").sync() as env:
    result = env.reset()
    result = env.step(IncidentAction(action_type=ActionType.CHECK_METRICS))
```

## Inference Script

`inference.py` runs a baseline agent against all tasks and prints strict lifecycle logs:

- `[START]`
- `[STEP]`
- `[END]`

Environment variables:

- `API_KEY`
- `API_BASE_URL`
- `MODEL_NAME`
- `ENV_BASE_URL`
- `LOCAL_IMAGE_NAME`

Run against a local server with the built-in heuristic policy:

```bash
python inference.py --server-url http://localhost:8000 --task all --no-openai
```

Run against a local server with a remote model:

```bash
API_KEY=... API_BASE_URL=... MODEL_NAME=Qwen/Qwen2.5-72B-Instruct \
python inference.py --server-url http://localhost:8000 --task all
```

Run against a Docker image instead of a running server:

```bash
LOCAL_IMAGE_NAME=incident-response-war-room \
API_KEY=... API_BASE_URL=... MODEL_NAME=Qwen/Qwen2.5-72B-Instruct \
python inference.py --task all
```

Run deterministic fallback without external API calls:

```bash
python inference.py --server-url http://localhost:8000 --task all --no-openai
```

## Docker

Build:

```bash
docker build -t incident-response-war-room -f Dockerfile .
```

Run:

```bash
docker run --rm -p 8000:8000 incident-response-war-room
```

## Hugging Face Spaces

This repository is prepared for Docker-based Hugging Face Spaces deployment:

- README frontmatter is included for Spaces
- `openenv.yaml` defines the OpenEnv runtime entrypoint
- `Dockerfile` at the repository root builds a self-contained runtime

Push from the environment root:

```bash
openenv push --repo-id <namespace>/incident-response-war-room
```

Actual deployment requires Hugging Face authentication and was not executed here.
