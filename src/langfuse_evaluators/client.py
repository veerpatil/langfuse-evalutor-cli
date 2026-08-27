import http.client
import json
from urllib.parse import urlparse

from .config import get_config

API_PATH = "/api/public/unstable/evaluators"
TIMEOUT_SECONDS = 30


def _get_connection(host_url: str) -> http.client.HTTPConnection:
    parsed = urlparse(host_url)
    host = parsed.netloc or parsed.path
    if parsed.scheme == "https":
        return http.client.HTTPSConnection(host, timeout=TIMEOUT_SECONDS)
    return http.client.HTTPConnection(host, timeout=TIMEOUT_SECONDS)


def _parse_response_body(body: str) -> dict:
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"message": body}


def create_evaluator(evaluator: dict, config: dict[str, str]) -> dict:
    """Create a single evaluator via the Langfuse API.

    Returns a dict with 'status', 'reason', and 'body' keys.
    """
    conn = _get_connection(config["host"])
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Basic {config['credentials']}",
    }

    try:
        conn.request("POST", API_PATH, body=json.dumps(evaluator), headers=headers)
        response = conn.getresponse()
        body = response.read().decode()
        return {
            "status": response.status,
            "reason": response.reason,
            "body": _parse_response_body(body),
        }
    except OSError as exc:
        return {
            "status": 0,
            "reason": exc.__class__.__name__,
            "body": {"message": str(exc)},
        }
    finally:
        conn.close()


def create_evaluators(evaluators: list[dict]) -> list[dict]:
    """Create multiple evaluators, returning results for each."""
    config = get_config()
    results = []
    for evaluator in evaluators:
        result = create_evaluator(evaluator, config)
        result["name"] = evaluator["name"]
        results.append(result)
    return results
