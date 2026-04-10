"""Proxy-only OpenAI client helpers."""

from __future__ import annotations

import os
from typing import Any

from openai import OpenAI


def get_llm_client(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> OpenAI:
    resolved_api_key = api_key or os.getenv("API_KEY")
    resolved_base_url = base_url or os.getenv("API_BASE_URL")

    if not resolved_base_url:
        raise SystemExit(
            "Remote inference requires API_BASE_URL. "
            "Use the injected LiteLLM proxy base URL or pass --no-openai."
        )
    if not resolved_api_key:
        raise SystemExit(
            "Remote inference requires API_KEY. "
            "Use the injected LiteLLM proxy key or pass --no-openai."
        )

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
