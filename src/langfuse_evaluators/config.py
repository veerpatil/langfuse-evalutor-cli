import os
import base64
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _load_env():
    """Load variables from .env file if it exists."""
    if ENV_FILE.exists():
        for line_number, line in enumerate(ENV_FILE.read_text().splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            if not key or not _:
                raise RuntimeError(f"Invalid .env entry on line {line_number}: {line}")
            os.environ.setdefault(key.strip(), value.strip())


def get_config() -> dict[str, str]:
    """Load and validate Langfuse configuration."""
    _load_env()

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
    host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")

    if not public_key or not secret_key:
        raise RuntimeError(
            "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set in .env or environment"
        )

    credentials = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()

    return {
        "host": host,
        "credentials": credentials,
    }


def _mlflow_authorization() -> str:
    """Build the optional ``Authorization`` header for MLflow.

    MLflow's own client reads ``MLFLOW_TRACKING_TOKEN`` for bearer auth and
    ``MLFLOW_TRACKING_USERNAME``/``MLFLOW_TRACKING_PASSWORD`` for HTTP
    Basic auth. Credentials are optional so a local tracking server keeps
    working; a token takes precedence when both forms are configured.
    Half-configured Basic credentials fail instead of silently sending an
    unauthenticated request.
    """
    token = os.environ.get("MLFLOW_TRACKING_TOKEN", "").strip()
    if token:
        return f"Bearer {token}"

    username = os.environ.get("MLFLOW_TRACKING_USERNAME", "").strip()
    password = os.environ.get("MLFLOW_TRACKING_PASSWORD", "")
    if not username and not password:
        return ""
    if not username or not password:
        raise RuntimeError(
            "MLFLOW_TRACKING_USERNAME and MLFLOW_TRACKING_PASSWORD must be "
            "set together"
        )

    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {credentials}"


def get_mlflow_config() -> dict[str, str]:
    """Load MLflow scorer configuration.

    ``MLFLOW_HOST`` defaults to the local MLflow tracking server.
    ``MLFLOW_EXPERIMENT_ID`` is the default experiment scorers are
    registered under and listed from; it may be omitted and supplied per
    call instead. Authentication is optional and read from
    ``MLFLOW_TRACKING_TOKEN`` or ``MLFLOW_TRACKING_USERNAME`` plus
    ``MLFLOW_TRACKING_PASSWORD``; ``authorization`` is present only when
    credentials are configured. None of these values require Langfuse
    credentials, so this is independent of :func:`get_config`.
    """
    _load_env()

    host = os.environ.get("MLFLOW_HOST", "http://localhost:5000")
    experiment_id = os.environ.get("MLFLOW_EXPERIMENT_ID", "")

    config = {
        "host": host,
        "experiment_id": experiment_id.strip(),
    }
    authorization = _mlflow_authorization()
    if authorization:
        config["authorization"] = authorization
    return config
