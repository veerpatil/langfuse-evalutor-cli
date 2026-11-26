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


def get_mlflow_config() -> dict[str, str]:
    """Load MLflow scorer configuration.

    ``MLFLOW_HOST`` defaults to the local MLflow tracking server.
    ``MLFLOW_EXPERIMENT_ID`` is the default experiment scorers are
    registered under and listed from; it may be omitted and supplied per
    call instead. Neither value requires Langfuse credentials, so this is
    independent of :func:`get_config`.
    """
    _load_env()

    host = os.environ.get("MLFLOW_HOST", "http://localhost:5000")
    experiment_id = os.environ.get("MLFLOW_EXPERIMENT_ID", "")

    return {
        "host": host,
        "experiment_id": experiment_id.strip(),
    }
