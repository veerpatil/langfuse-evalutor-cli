"""Shared pytest fixtures for the langfuse_evaluators test suite."""

from __future__ import annotations

import pytest
from helpers import FakeConnection

from langfuse_evaluators import client as client_module
from langfuse_evaluators.mlflow_scorers import client as mlflow_client_module


@pytest.fixture
def config() -> dict[str, str]:
    """A resolved config with a Basic auth credential already encoded."""
    return {
        "host": "http://localhost:3000",
        "credentials": "dummy-basic-credentials",
    }


@pytest.fixture
def connection(monkeypatch):
    """Install a fake connection factory and return an install callback."""

    def install(*responses) -> FakeConnection:
        fake = FakeConnection(responses)
        monkeypatch.setattr(client_module, "_get_connection", lambda host: fake)
        return fake

    return install


@pytest.fixture
def mlflow_config() -> dict[str, str]:
    """A resolved MLflow config with a default experiment id."""
    return {
        "host": "http://localhost:5000",
        "experiment_id": "exp-1",
    }


@pytest.fixture
def mlflow_connection(monkeypatch):
    """Install a fake connection factory for the MLflow client."""

    def install(*responses) -> FakeConnection:
        fake = FakeConnection(responses)
        monkeypatch.setattr(
            mlflow_client_module, "_get_connection", lambda host: fake
        )
        return fake

    return install
