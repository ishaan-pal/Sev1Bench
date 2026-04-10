import importlib
import sys

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
