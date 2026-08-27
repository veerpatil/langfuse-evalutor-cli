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
