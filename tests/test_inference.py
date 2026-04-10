import importlib
import sys
from types import SimpleNamespace

import pytest


def import_inference_with_clean_proxy_env(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("API_BASE_URL", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    sys.modules.pop("inference", None)
    return importlib.import_module("inference")


def test_parse_args_reads_proxy_env_at_runtime(monkeypatch):
    inference = import_inference_with_clean_proxy_env(monkeypatch)

    monkeypatch.setenv("API_KEY", "runtime-key")
    monkeypatch.setenv("API_BASE_URL", "https://proxy.example/v1")
    monkeypatch.setenv("MODEL_NAME", "openai/gpt-4.1-mini")
    monkeypatch.setattr(sys, "argv", ["inference.py"])

    args = inference.parse_args()

    assert args.api_key == "runtime-key"
    assert args.api_base_url == "https://proxy.example/v1"
    assert args.model_name == "openai/gpt-4.1-mini"


def test_create_client_requires_proxy_env(monkeypatch):
    inference = import_inference_with_clean_proxy_env(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["inference.py"])

    args = inference.parse_args()

    with pytest.raises(SystemExit, match="API_BASE_URL"):
        inference.create_client(args)


def test_create_client_uses_shared_proxy_client(monkeypatch):
    inference = import_inference_with_clean_proxy_env(monkeypatch)
    monkeypatch.setenv("API_KEY", "runtime-key")
    monkeypatch.setenv("API_BASE_URL", "https://proxy.example/v1")
    monkeypatch.setattr(sys, "argv", ["inference.py"])

    args = inference.parse_args()
    client = inference.create_client(args)

    assert str(client.base_url) == "https://proxy.example/v1/"


def test_chat_completion_logs_proxy_route(capsys):
    client_module = importlib.import_module("client")

    fake_client = SimpleNamespace(
        base_url="https://proxy.example/v1",
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: {"ok": True, "kwargs": kwargs}
            )
        ),
    )

    result = client_module.chat_completion(
        client=fake_client,
        model="qwen",
        messages=[{"role": "user", "content": "ping"}],
        temperature=0,
    )

    captured = capsys.readouterr()

    assert "LLM CALL ROUTED THROUGH PROXY: https://proxy.example/v1" in captured.out
    assert result["kwargs"]["model"] == "qwen"
