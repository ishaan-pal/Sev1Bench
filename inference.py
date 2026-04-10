"""Inference runner for Incident Response War Room."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import textwrap
from typing import Optional

from client import IncidentResponseWarRoomEnv, chat_completion, get_llm_client
from models import ActionType, IncidentAction, ServiceName
from tasks import list_task_ids

# Environment variables (as required by hackathon checklist)
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:4000")
MODEL_NAME = os.getenv("MODEL_NAME", "huggingface/Qwen/Qwen2.5-72B-Instruct")
HF_TOKEN = os.getenv("HF_TOKEN")
LOCAL_IMAGE_NAME = os.getenv("LOCAL_IMAGE_NAME")

DEFAULT_MODEL_NAME = "huggingface/Qwen/Qwen2.5-72B-Instruct"
DEFAULT_BENCHMARK = "incident_response_war_room"
DEFAULT_MAX_STEPS = 8
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 250
SUCCESS_SCORE_THRESHOLD = 0.1

SYSTEM_PROMPT = textwrap.dedent(
    """
    You are the on-call engineer in an incident-response environment.
    Return exactly one compact JSON object with keys:
    - action_type: one of check_metrics, check_logs, restart_service, scale_service, do_nothing
    - service: null, api, or database

    Rules:
    - Use check_metrics first when metrics are unknown.
    - Use check_logs when metrics suggest a hidden dependency problem.
    - For obvious API CPU saturation, scale_service on api.
    - For connection leaks or lock storms in logs, restart_service on database.
    - For cascading failure, stabilize database before scaling api.
    """
).strip()


def env_or_default(name: str, default: str | None = None) -> str | None:
    return os.getenv(name) or default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task",
        default=env_or_default("INCIDENT_RESPONSE_WAR_ROOM_TASK", "all"),
        help="Task id to run, or 'all'.",
    )
    parser.add_argument(
        "--benchmark",
        default=env_or_default(
            "INCIDENT_RESPONSE_WAR_ROOM_BENCHMARK", DEFAULT_BENCHMARK
        ),
        help="Benchmark label used in logs.",
    )
    parser.add_argument(
        "--model-name",
        default=env_or_default("MODEL_NAME", DEFAULT_MODEL_NAME),
        help="Model name for remote inference.",
    )
    parser.add_argument(
        "--server-url",
        default=env_or_default("ENV_BASE_URL"),
        help="Use an already running environment server instead of launching Docker.",
    )
    parser.add_argument(
        "--local-image-name",
        default=env_or_default("LOCAL_IMAGE_NAME"),
        help="Docker image name used when launching the environment via OpenEnv.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=int(env_or_default("MAX_STEPS", str(DEFAULT_MAX_STEPS))),
        help="Maximum number of agent steps to take per episode.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=float(env_or_default("TEMPERATURE", str(DEFAULT_TEMPERATURE))),
        help="Sampling temperature for remote model calls.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(env_or_default("MAX_TOKENS", str(DEFAULT_MAX_TOKENS))),
        help="Maximum tokens for remote model calls.",
    )
    parser.add_argument(
        "--no-openai",
        action="store_true",
        help="Disable remote model calls and use the built-in heuristic policy.",
    )
    return parser.parse_args()


def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(
    step: int, action: str, reward: float, done: bool, error: Optional[str]
) -> None:
    error_val = error if error else "null"
    done_val = str(done).lower()
    print(
        f"[STEP] step={step} action={action} reward={reward:.2f} done={done_val} error={error_val}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: list[float]) -> None:
    rewards_str = ",".join(f"{reward:.2f}" for reward in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} score={score:.2f} rewards={rewards_str}",
        flush=True,
    )


def format_action(action: IncidentAction) -> str:
    if action.service is None:
        return f"{action.action_type.value}()"
    return f"{action.action_type.value}({action.service.value})"


def heuristic_action(observation: dict, state_health: float) -> IncidentAction:
    visible_metrics = observation.get("visible_metrics", {})
    visible_logs = observation.get("visible_logs", {})
    summary = observation.get("summary", "").lower()
    task_id = observation.get("task_id", "")

    api_metrics = visible_metrics.get("api")
    db_metrics = visible_metrics.get("database")
    log_text = " ".join(
        line.lower() for lines in visible_logs.values() for line in lines
    )

    if "connection pool exhausted" in log_text or "leaked sessions" in log_text:
        return IncidentAction(
            action_type=ActionType.RESTART_SERVICE, service=ServiceName.DATABASE
        )
    if "lock wait timeout" in log_text or "lock storm" in log_text:
        return IncidentAction(
            action_type=ActionType.RESTART_SERVICE, service=ServiceName.DATABASE
        )
    if "drain the backlog" in log_text or (
        "database recovery" in log_text and state_health < 84.0
    ):
        return IncidentAction(
            action_type=ActionType.SCALE_SERVICE, service=ServiceName.API
        )

    if not visible_metrics:
        return IncidentAction(action_type=ActionType.CHECK_METRICS)

    if task_id == "easy_cpu_overload":
        if api_metrics and api_metrics["cpu"] >= 80.0:
            return IncidentAction(
                action_type=ActionType.SCALE_SERVICE, service=ServiceName.API
            )
        return IncidentAction(action_type=ActionType.DO_NOTHING)

    if not visible_logs and db_metrics and db_metrics["latency_ms"] >= 150.0:
        return IncidentAction(action_type=ActionType.CHECK_LOGS)

    if "incident resolved" in summary:
        return IncidentAction(action_type=ActionType.DO_NOTHING)

    if (
        task_id == "hard_cascading_failure"
        and db_metrics
        and db_metrics["latency_ms"] < 180.0
        and api_metrics
        and api_metrics["latency_ms"] > 250.0
    ):
        return IncidentAction(
            action_type=ActionType.SCALE_SERVICE, service=ServiceName.API
        )

    return IncidentAction(action_type=ActionType.DO_NOTHING)


def build_user_prompt(
    task_name: str,
    observation: dict,
    state_health: float,
    step: int,
    history: list[str],
) -> str:
    history_block = "\n".join(history[-4:]) if history else "None"
    return textwrap.dedent(
        f"""
        Task: {task_name}
        Step: {step}
        Health score: {state_health:.2f}
        Observation:
        {json.dumps(observation, sort_keys=True)}

        Recent history:
        {history_block}

        Return the best next action as JSON.
        """
    ).strip()


def get_model_action(
    client,
    task_name: str,
    observation: dict,
    state_health: float,
    step: int,
    history: list[str],
    model_name: str,
    temperature: float,
    max_tokens: int,
) -> IncidentAction:
    if client is None:
        return heuristic_action(observation, state_health)

    user_prompt = build_user_prompt(task_name, observation, state_health, step, history)
    try:
        completion = chat_completion(
            client=client,
            model=model_name,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        content = (completion.choices[0].message.content or "").strip()
        data = json.loads(content) if content else {}
        return IncidentAction(
            action_type=ActionType(data["action_type"]),
            service=(
                None
                if data.get("service") in (None, "null")
                else ServiceName(data["service"])
            ),
        )
    except Exception:
        return heuristic_action(observation, state_health)


async def create_env(args: argparse.Namespace) -> IncidentResponseWarRoomEnv:
    if args.server_url:
        return IncidentResponseWarRoomEnv(base_url=args.server_url)
    if args.local_image_name:
        return await IncidentResponseWarRoomEnv.from_docker_image(args.local_image_name)
    raise RuntimeError(
        "Set --server-url/ENV_BASE_URL for a running server or "
        "--local-image-name/LOCAL_IMAGE_NAME for Docker-backed inference."
    )


def create_client(args: argparse.Namespace):
    if args.no_openai:
        return None
    # Use hackathon-injected credentials via os.getenv (set at module top)
    return get_llm_client(
        api_key=HF_TOKEN,
        base_url=API_BASE_URL,
    )


async def run_episode(client, task_name: str, args: argparse.Namespace) -> None:
    env: IncidentResponseWarRoomEnv | None = None
    rewards: list[float] = []
    steps_taken = 0
    score = 0.0
    success = False

    log_start(task=task_name, env=args.benchmark, model=args.model_name)

    try:
        env = await create_env(args)
        result = await env.reset(task_id=task_name)
        state = await env.state()
        max_steps = min(args.max_steps, state.max_steps or args.max_steps)
        history: list[str] = []

        for step in range(1, max_steps + 1):
            observation_payload = result.observation.model_dump(mode="json")
            # Keep the event loop responsive while waiting on a synchronous model API call.
            action = await asyncio.to_thread(
                get_model_action,
                client=client,
                task_name=task_name,
                observation=observation_payload,
                state_health=state.health_score,
                step=step,
                history=history,
                model_name=args.model_name,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
            )

            error: Optional[str] = None
            try:
                result = await env.step(action)
                state = await env.state()
                reward = float(result.reward or 0.0)
                done = bool(result.done)
            except Exception as exc:
                reward = 0.0
                done = True
                error = str(exc)

            rewards.append(reward)
            steps_taken = step
            log_step(
                step=step,
                action=format_action(action),
                reward=reward,
                done=done,
                error=error,
            )

            history.append(
                f"step={step} action={format_action(action)} reward={reward:.2f} error={error or 'null'}"
            )

            if done:
                break

        if env is not None:
            final_state = await env.state()
            score = max(0.0, min(1.0, float(final_state.grader_score)))
            success = bool(final_state.resolved or score >= SUCCESS_SCORE_THRESHOLD)
    except Exception as exc:
        log_step(
            step=max(1, steps_taken),
            action="setup()",
            reward=0.0,
            done=True,
            error=str(exc),
        )
        success = False
    finally:
        if env is not None:
            await env.close()
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)


async def main() -> None:
    args = parse_args()
    client = create_client(args)

    if args.task == "all":
        task_names = list_task_ids()
    else:
        task_names = [args.task]

    for task_name in task_names:
        await run_episode(client, task_name, args)


if __name__ == "__main__":
    asyncio.run(main())