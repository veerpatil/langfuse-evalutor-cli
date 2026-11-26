"""Tests for the configuration loader."""

from __future__ import annotations

import base64

import pytest

from langfuse_evaluators import config as config_module


@pytest.fixture(autouse=True)
def no_env_file(monkeypatch, tmp_path):
    """Keep a developer's local .env file out of the tests."""
    monkeypatch.setattr(config_module, "ENV_FILE", tmp_path / "missing.env")


def test_get_config_builds_basic_credentials(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.example.com")

    config = config_module.get_config()

    expected = base64.b64encode(b"pk-lf-test:sk-lf-test").decode()
    assert config == {
        "host": "https://langfuse.example.com",
        "credentials": expected,
    }


def test_get_config_defaults_to_local_host(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)

    assert config_module.get_config()["host"] == "http://localhost:3000"


def test_get_config_requires_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError):
        config_module.get_config()


def test_get_mlflow_config_reads_host_and_experiment(monkeypatch):
    monkeypatch.setenv("MLFLOW_HOST", "https://mlflow.example.com")
    monkeypatch.setenv("MLFLOW_EXPERIMENT_ID", "42")

    assert config_module.get_mlflow_config() == {
        "host": "https://mlflow.example.com",
        "experiment_id": "42",
    }


def test_get_mlflow_config_defaults_to_the_local_tracking_server(monkeypatch):
    monkeypatch.delenv("MLFLOW_HOST", raising=False)
    monkeypatch.delenv("MLFLOW_EXPERIMENT_ID", raising=False)

    assert config_module.get_mlflow_config() == {
        "host": "http://localhost:5000",
        "experiment_id": "",
    }


def test_get_mlflow_config_does_not_require_langfuse_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    assert config_module.get_mlflow_config()["host"] == "http://localhost:5000"
