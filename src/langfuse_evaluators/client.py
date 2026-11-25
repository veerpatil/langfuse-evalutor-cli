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
from collections.abc import Callable, Iterator, Mapping
from typing import Any
from urllib.parse import ParseResult, quote, urlencode, urlparse

from .config import get_config
from .errors import (
    LangfuseAPIError,
    LangfuseError,
    LangfuseResponseError,
    LangfuseTransportError,
)
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


def _parse_host(host_url: str) -> ParseResult:
    """Parse ``LANGFUSE_HOST``, rejecting hosts without an http(s) scheme.

    A schemeless host (``example.com``) produces an empty netloc, so the
    request line ends up carrying the bare host instead of an origin-form
    path and servers reject or misroute it. Fail before the request is
    sent. The value is never echoed because a host can embed credentials.
    """
    parsed = urlparse(host_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise LangfuseError("LANGFUSE_HOST must start with http:// or https://")
    return parsed


def _get_connection(host_url: str) -> http.client.HTTPConnection:
    parsed = _parse_host(host_url)
    if parsed.scheme == "https":
        return http.client.HTTPSConnection(parsed.netloc, timeout=TIMEOUT_SECONDS)
    return http.client.HTTPConnection(parsed.netloc, timeout=TIMEOUT_SECONDS)


def _base_path(host_url: str) -> str:
    """Return the path a self-hosted Langfuse instance is mounted under.

    ``LANGFUSE_HOST`` may include a path prefix (for example
    ``https://example.com/langfuse``); that prefix has to be prepended to
    every API path so path-mounted deployments are not sent to the server
    root.
    """
    return _parse_host(host_url).path.rstrip("/")


def _build_url(host_url: str, path: str, query: Mapping[str, Any] | None = None) -> str:
    """Join the configured host, the API path, and any query parameters.

    Host parsing, path-prefix handling, and query encoding live here so a
    URL change is made in one place.
    """
    url = f"{_base_path(host_url)}{path}"
    if not query:
        return url
    params = {key: value for key, value in query.items() if value is not None}
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


def _authorization_header(config: Mapping[str, str]) -> str:
    """Build the Basic auth header, rejecting unsafe credential values.

    Credentials normally come base64-encoded from ``get_config``, but the
    client functions accept an arbitrary mapping. Control characters
    would allow header injection, and ``http.client`` errors can echo the
    value, so fail before the request is sent instead.
    """
    credentials = config.get("credentials", "")
    if (
        not isinstance(credentials, str)
        or not credentials
        or not credentials.isascii()
        or not credentials.isprintable()
    ):
        raise LangfuseError(
            "Langfuse credentials are missing or contain invalid characters"
        )
    return f"Basic {credentials}"


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
    url = _build_url(config["host"], path, query)

    headers = {
        "Accept": "application/json",
        "Authorization": _authorization_header(config),
    }
    payload = None
    if body is not None:
        payload = json.dumps(body)
        headers["Content-Type"] = "application/json"

    conn = _get_connection(config["host"])
    try:
        conn.request(method, url, body=payload, headers=headers)
        response = conn.getresponse()
        # A non-UTF-8 body must not escape the transport wrapping, so
        # decode leniently and let the response models reject the payload.
        raw_body = response.read().decode("utf-8", errors="replace")
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
    """Accept both a bare object and an object wrapped in ``data``.

    The upstream v2 reference was unreachable when this client was
    written, so both response shapes are tolerated until the live
    contract can be confirmed. Pin this to the documented shape and drop
    the fallback once verified against a real v2 instance.

    TODO(#2): remove the bare-object fallback once the v2 response shape
    is confirmed against a live instance.
    """
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


class _UnreadableCreateResponse(LangfuseResponseError):
    """A 2xx create response whose payload has no evaluator id.

    The evaluator exists server-side, so this is reported separately from
    a pre-request failure: it carries the real HTTP status and tells the
    caller to check the listing before retrying, which avoids creating a
    duplicate.
    """

    reason_token = "ResponseParseError"

    def __init__(self, status: int, reason: str, cause: BaseException) -> None:
        self.status = status
        self.reason = reason
        super().__init__(
            f"The evaluator was created (HTTP {status} {reason or 'response'}) "
            "but its evaluator id could not be read; run "
            "`create-evaluators list` before retrying "
            f"({cause.__class__.__name__}: {cause})"
        )

    def to_result(self) -> dict:
        """Return the historical CLI result shape for this failure."""
        return {
            "status": self.status,
            "reason": self.reason_token,
            "body": {"message": str(self)},
        }


def create_evaluator(
    evaluator: Mapping[str, Any], config: Mapping[str, str]
) -> Evaluator:
    """Create an evaluator and return it with its new ``evaluatorId``."""
    _, _, created = _create_evaluator_with_status(evaluator, config)
    return created


def create_evaluator_result(
    evaluator: Mapping[str, Any], config: Mapping[str, str]
) -> dict:
    """Create an evaluator and return the legacy 0.1.0 result dict.

    Compatibility shim for callers written against ``0.1.0``, when
    ``create_evaluator`` returned ``{status, reason, body}`` and reported
    HTTP failures in that dict instead of raising. New code should call
    :func:`create_evaluator` and handle the typed errors instead.
    """
    try:
        status, reason, created = _create_evaluator_with_status(evaluator, config)
    except LangfuseAPIError as exc:
        return exc.to_result()
    except LangfuseTransportError as exc:
        return _failure_result(exc.cause)
    except _UnreadableCreateResponse as exc:
        return exc.to_result()
    except (ValueError, TypeError, LangfuseError) as exc:
        return _failure_result(exc)
    return {"status": status, "reason": reason, "body": created.to_dict()}


def _create_evaluator_with_status(
    evaluator: Mapping[str, Any], config: Mapping[str, str]
) -> tuple[int, str, Evaluator]:
    payload = validate_evaluator_payload(evaluator)
    status, reason, body = _request("POST", API_PATH, config, body=payload)
    try:
        return status, reason, Evaluator.from_api(_unwrap_object(body))
    except LangfuseResponseError as exc:
        raise _UnreadableCreateResponse(status, reason, exc) from exc


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


def _iter_pages(
    fetch_page: Callable[[str | None], Any],
    key: Callable[[Any], Any],
    cursor: str | None = None,
) -> Iterator[Any]:
    """Yield de-duplicated items across cursor pages.

    ``fetch_page`` requests one page starting at the given cursor and
    ``key`` identifies an item for de-duplication. Iteration stops when
    the API stops returning a cursor or repeats a cursor it already
    returned, which keeps a misbehaving page from looping forever.
    """
    seen_keys: set[Any] = set()
    # Seed the set with the caller's cursor so an API that echoes it back
    # terminates after the first page instead of fetching it again.
    seen_cursors: set[str] = {cursor} if cursor is not None else set()

    while True:
        page = fetch_page(cursor)
        for item in page.data:
            marker = key(item)
            if marker in seen_keys:
                continue
            seen_keys.add(marker)
            yield item

        if not page.cursor or page.cursor in seen_cursors:
            return
        seen_cursors.add(page.cursor)
        cursor = page.cursor


def iter_evaluators(
    config: Mapping[str, str],
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> Iterator[Evaluator]:
    """Yield evaluators from ``cursor`` onward, de-duplicating by id."""
    yield from _iter_pages(
        lambda page_cursor: list_evaluators(config, limit=limit, cursor=page_cursor),
        lambda evaluator: evaluator.evaluator_id,
        cursor,
    )


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
    cursor: str | None = None,
) -> Iterator[EvaluatorVersion]:
    """Yield an evaluator's versions from ``cursor`` onward."""
    yield from _iter_pages(
        lambda page_cursor: list_evaluator_versions(
            evaluator_id, config, limit=limit, cursor=page_cursor
        ),
        lambda version: version.version,
        cursor,
    )


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
            status, reason, created = _create_evaluator_with_status(evaluator, config)
        except LangfuseAPIError as exc:
            results.append({**exc.to_result(), **_result_identity(name)})
            continue
        except LangfuseTransportError as exc:
            results.append({**_failure_result(exc.cause), **_result_identity(name)})
            continue
        except _UnreadableCreateResponse as exc:
            results.append({**exc.to_result(), **_result_identity(name)})
            continue
        except (ValueError, TypeError, LangfuseError) as exc:
            # Invalid payloads (ValueError), values json.dumps cannot
            # serialise (TypeError), and unusable credentials
            # (LangfuseError) all fail before a response is read, so one bad
            # evaluator is reported without aborting the batch.
            results.append({**_failure_result(exc), **_result_identity(name)})
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


def _failure_result(exc: BaseException) -> dict:
    """Return the historical status-0 result shape for a failure."""
    return {
        "status": 0,
        "reason": exc.__class__.__name__,
        "body": {"message": str(exc)},
    }


def _result_identity(name: str, evaluator: Evaluator | None = None) -> dict:
    return {
        "name": name,
        "evaluatorId": evaluator.evaluator_id if evaluator else None,
        "version": evaluator.version if evaluator else None,
    }
