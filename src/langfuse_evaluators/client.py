"""HTTP client for the stable Langfuse v2 evaluators API.

The v2 contract exposed at ``/api/public/v2/evaluators`` replaces the
previous unstable, create-only endpoint. Evaluators are addressed by
their stable ``evaluatorId``, listing is cursor based, and every failure
carries a structured error body that the client maps onto stable error
kinds instead of parsing message text.
"""

from __future__ import annotations

import http.client
import json
from collections.abc import Iterator, Mapping
from typing import Any
from urllib.parse import quote, urlencode, urlparse

from .config import get_config
from .errors import LangfuseAPIError, LangfuseTransportError
from .models import (
    Evaluator,
    EvaluatorPage,
    EvaluatorVersion,
    EvaluatorVersionPage,
    validate_evaluator_payload,
)

API_PATH = "/api/public/v2/evaluators"
TIMEOUT_SECONDS = 30
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


def _get_connection(host_url: str) -> http.client.HTTPConnection:
    parsed = urlparse(host_url)
    host = parsed.netloc or parsed.path
    if parsed.scheme == "https":
        return http.client.HTTPSConnection(host, timeout=TIMEOUT_SECONDS)
    return http.client.HTTPConnection(host, timeout=TIMEOUT_SECONDS)


def _parse_response_body(body: str) -> Any:
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"message": body}


def _request(
    method: str,
    path: str,
    config: Mapping[str, str],
    body: Any = None,
    query: Mapping[str, Any] | None = None,
) -> tuple[int, str, Any]:
    """Send one authenticated request and return ``(status, reason, body)``.

    Raises ``LangfuseAPIError`` for a non-2xx response and
    ``LangfuseTransportError`` when no HTTP response is produced. A body
    that is not valid JSON is returned as ``{"message": <raw body>}`` so
    callers can surface it; the response models reject it where a
    structured payload is required.
    """
    url = path
    if query:
        params = {key: value for key, value in query.items() if value is not None}
        if params:
            url = f"{path}?{urlencode(params)}"

    headers = {
        "Accept": "application/json",
        "Authorization": f"Basic {config['credentials']}",
    }
    payload = None
    if body is not None:
        payload = json.dumps(body)
        headers["Content-Type"] = "application/json"

    conn = _get_connection(config["host"])
    try:
        conn.request(method, url, body=payload, headers=headers)
        response = conn.getresponse()
        raw_body = response.read().decode()
        status = response.status
        reason = response.reason
    except (OSError, http.client.HTTPException) as exc:
        raise LangfuseTransportError(method, path, exc) from exc
    finally:
        conn.close()

    if not 200 <= status < 300:
        raise LangfuseAPIError(
            status, reason, _parse_response_body(raw_body), method, path
        )

    return status, reason, _parse_response_body(raw_body)


def _unwrap_object(body: Any) -> Any:
    """Accept both a bare object and an object wrapped in ``data``."""
    if isinstance(body, Mapping) and isinstance(body.get("data"), Mapping):
        return body["data"]
    return body


def _evaluator_path(evaluator_id: str, suffix: str = "") -> str:
    if not isinstance(evaluator_id, str) or not evaluator_id.strip():
        raise ValueError("evaluator_id must be a non-empty string")
    return f"{API_PATH}/{quote(evaluator_id.strip(), safe='')}{suffix}"


def _validate_page_size(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")


def create_evaluator(
    evaluator: Mapping[str, Any], config: Mapping[str, str]
) -> Evaluator:
    """Create an evaluator and return it with its new ``evaluatorId``."""
    _, _, created = _create_evaluator(evaluator, config)
    return created


def _create_evaluator(
    evaluator: Mapping[str, Any], config: Mapping[str, str]
) -> tuple[int, str, Evaluator]:
    payload = validate_evaluator_payload(evaluator)
    status, reason, body = _request("POST", API_PATH, config, body=payload)
    return status, reason, Evaluator.from_api(_unwrap_object(body))


def get_evaluator(evaluator_id: str, config: Mapping[str, str]) -> Evaluator:
    """Retrieve a single evaluator by its stable id."""
    _, _, body = _request("GET", _evaluator_path(evaluator_id), config)
    return Evaluator.from_api(_unwrap_object(body))


def update_evaluator(
    evaluator_id: str, changes: Mapping[str, Any], config: Mapping[str, str]
) -> Evaluator:
    """Apply ``changes`` to an evaluator and return the new revision."""
    if not isinstance(changes, Mapping) or not changes:
        raise ValueError("changes must be a non-empty mapping")
    payload = dict(changes)
    _, _, body = _request("PUT", _evaluator_path(evaluator_id), config, body=payload)
    return Evaluator.from_api(_unwrap_object(body))


def delete_evaluator(evaluator_id: str, config: Mapping[str, str]) -> None:
    """Delete an evaluator by its stable id."""
    _request("DELETE", _evaluator_path(evaluator_id), config)


def list_evaluators(
    config: Mapping[str, str],
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> EvaluatorPage:
    """List one page of evaluators and return its next cursor."""
    _validate_page_size(limit)
    _, _, body = _request(
        "GET", API_PATH, config, query={"limit": limit, "cursor": cursor}
    )
    return EvaluatorPage.from_api(body)


def iter_evaluators(
    config: Mapping[str, str], limit: int = DEFAULT_PAGE_SIZE
) -> Iterator[Evaluator]:
    """Yield every evaluator, following cursors and de-duplicating by id.

    Iteration stops when the API stops returning a cursor or repeats a
    cursor it already returned, which keeps a misbehaving page from
    looping forever.
    """
    seen_ids: set[str] = set()
    seen_cursors: set[str] = set()
    cursor: str | None = None

    while True:
        page = list_evaluators(config, limit=limit, cursor=cursor)
        for evaluator in page.data:
            if evaluator.evaluator_id in seen_ids:
                continue
            seen_ids.add(evaluator.evaluator_id)
            yield evaluator

        if not page.cursor or page.cursor in seen_cursors:
            return
        seen_cursors.add(page.cursor)
        cursor = page.cursor


def list_evaluator_versions(
    evaluator_id: str,
    config: Mapping[str, str],
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> EvaluatorVersionPage:
    """List one page of an evaluator's version history."""
    _validate_page_size(limit)
    _, _, body = _request(
        "GET",
        _evaluator_path(evaluator_id, "/versions"),
        config,
        query={"limit": limit, "cursor": cursor},
    )
    return EvaluatorVersionPage.from_api(body, evaluator_id)


def iter_evaluator_versions(
    evaluator_id: str,
    config: Mapping[str, str],
    limit: int = DEFAULT_PAGE_SIZE,
) -> Iterator[EvaluatorVersion]:
    """Yield every version of an evaluator, following cursors."""
    seen_versions: set[int] = set()
    seen_cursors: set[str] = set()
    cursor: str | None = None

    while True:
        page = list_evaluator_versions(evaluator_id, config, limit=limit, cursor=cursor)
        for version in page.data:
            if version.version in seen_versions:
                continue
            seen_versions.add(version.version)
            yield version

        if not page.cursor or page.cursor in seen_cursors:
            return
        seen_cursors.add(page.cursor)
        cursor = page.cursor


def create_evaluators(evaluators: list[Mapping[str, Any]]) -> list[dict]:
    """Create multiple evaluators, returning one result per evaluator.

    This is the entry point used by the ``create-evaluators`` CLI. Each
    result keeps the historical ``status`` / ``reason`` / ``body`` /
    ``name`` keys and adds the stable ``evaluatorId`` and ``version``
    returned by the v2 API. Failures are reported per evaluator so one
    rejected evaluator does not abort the batch.
    """
    config = get_config()
    results = []
    for evaluator in evaluators:
        name = evaluator.get("name", "") if isinstance(evaluator, Mapping) else ""
        try:
            status, reason, created = _create_evaluator(evaluator, config)
        except LangfuseAPIError as exc:
            results.append({**exc.to_result(), **_result_identity(name)})
            continue
        except LangfuseTransportError as exc:
            results.append(
                {
                    "status": 0,
                    "reason": exc.cause.__class__.__name__,
                    "body": {"message": str(exc.cause)},
                    **_result_identity(name),
                }
            )
            continue
        except ValueError as exc:
            # Covers invalid payloads (ValueError) and unusable 2xx bodies
            # (LangfuseResponseError, a ValueError subclass).
            results.append(
                {
                    "status": 0,
                    "reason": "MalformedRequestOrResponse",
                    "body": {"message": str(exc)},
                    **_result_identity(name),
                }
            )
            continue

        results.append(
            {
                "status": status,
                "reason": reason,
                "body": created.to_dict(),
                **_result_identity(created.name or name, created),
            }
        )
    return results


def _result_identity(name: str, evaluator: Evaluator | None = None) -> dict:
    return {
        "name": name,
        "evaluatorId": evaluator.evaluator_id if evaluator else None,
        "version": evaluator.version if evaluator else None,
    }
