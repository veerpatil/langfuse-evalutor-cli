"""HTTP client for the MLflow scorer API.

The scorer endpoints live under ``/api/3.0/mlflow/scorers``. A scorer is
scoped to an experiment and addressed by ``(experiment_id, name)``;
registration assigns a stable ``scorer_id`` and a new ``version``, and
deleting without a version removes every version of that scorer. Failures
are mapped onto the same stable error kinds the Langfuse client uses.

The request shapes follow the MLflow tracking-server contract: ``register``
is a JSON POST, ``list``/``versions``/``get`` are GETs whose parameters are
sent as query string values, and ``delete`` is a DELETE with a JSON body.
Authentication is optional and supplied by ``get_mlflow_config`` as an
``authorization`` value, which is sent as the ``Authorization`` header.
Credentials are never sent over plaintext HTTP to a non-local host, so a
misconfigured ``MLFLOW_HOST`` fails closed instead of leaking them.
"""

from __future__ import annotations

import http.client
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import ParseResult, urlencode, urlparse

from .errors import (
    MLflowAPIError,
    MLflowError,
    MLflowTransportError,
)
from .models import Scorer, scorers_from_list, validate_scorer_payload

API_PATH = "/api/3.0/mlflow/scorers"
TIMEOUT_SECONDS = 30


def _parse_host(host_url: str) -> ParseResult:
    """Parse ``MLFLOW_HOST``, rejecting unsupported or unsafe hosts.

    A schemeless value produces an empty netloc, so the request line
    carries the bare host instead of an origin-form path and servers
    reject or misroute it. Fail before the request is sent. The value is
    never echoed because a host can embed credentials.
    """
    parsed = urlparse(host_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise MLflowError("MLFLOW_HOST must start with http:// or https://")
    if parsed.username is not None or parsed.password is not None:
        raise MLflowError(
            "MLFLOW_HOST must not embed credentials; set the MLflow host "
            "without userinfo"
        )
    if parsed.query or parsed.fragment:
        raise MLflowError(
            "MLFLOW_HOST must not contain a query string or fragment; only a "
            "host and an optional path prefix are supported"
        )
    try:
        parsed.port
    except ValueError as exc:
        raise MLflowError("MLFLOW_HOST has an invalid port") from exc
    return parsed


# Hosts for which a plaintext ``http://`` origin stays inside the machine,
# so sending credentials there cannot expose them on the network.
_LOCAL_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def _require_secure_transport(host_url: str, authorization: str | None) -> None:
    """Refuse to send MLflow credentials over plaintext HTTP.

    A local tracking server defaults to ``http://localhost``, so an
    unauthenticated or loopback plaintext host keeps working. Once
    credentials are configured, an ``http://`` host outside loopback would
    put the credential and the scorer payloads on the wire in the clear,
    so the request fails closed instead.
    """
    if not authorization:
        return
    parsed = _parse_host(host_url)
    if parsed.scheme != "http":
        return
    if (parsed.hostname or "").lower() in _LOCAL_HOSTNAMES:
        return
    raise MLflowError(
        "refusing to send MLflow credentials over plaintext HTTP; use an "
        "https:// MLFLOW_HOST (only a localhost host may stay on http://) or "
        "unset the MLflow credentials"
    )


def _get_connection(host_url: str) -> http.client.HTTPConnection:
    parsed = _parse_host(host_url)
    if parsed.scheme == "https":
        return http.client.HTTPSConnection(parsed.netloc, timeout=TIMEOUT_SECONDS)
    return http.client.HTTPConnection(parsed.netloc, timeout=TIMEOUT_SECONDS)


def _base_path(host_url: str) -> str:
    """Return the path an MLflow tracking server is mounted under."""
    return _parse_host(host_url).path.rstrip("/")


def _build_url(host_url: str, path: str, query: Mapping[str, Any] | None = None) -> str:
    """Join the configured host, the API path, and any query parameters.

    Parameters whose value is ``None`` are omitted so an optional parameter
    such as ``version`` can mean "not sent".
    """
    url = f"{_base_path(host_url)}{path}"
    if not query:
        return url
    params = {key: value for key, value in query.items() if value is not None}
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


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
    """Send one request and return ``(status, reason, body)``.

    Raises ``MLflowAPIError`` for a non-2xx response and
    ``MLflowTransportError`` when no HTTP response is produced. A body
    that is not valid JSON is returned as ``{"message": <raw body>}`` so
    callers can surface it; the response models reject it where a
    structured payload is required.

    Credentials are optional: when ``get_mlflow_config`` resolved a bearer
    token or Basic key pair, its ``authorization`` value is sent verbatim.
    Sending it to a non-local ``http://`` host is refused so credentials are
    never transmitted in the clear.
    """
    url = _build_url(config["host"], path, query)

    headers = {"Accept": "application/json"}
    authorization = config.get("authorization")
    if authorization:
        _require_secure_transport(config["host"], authorization)
        headers["Authorization"] = authorization
    payload = None
    if body is not None:
        payload = json.dumps(body)
        # MLflow parses the register and delete bodies as JSON, so send
        # the content type with every request that carries one.
        headers["Content-Type"] = "application/json"

    conn = None
    try:
        # Connection construction is inside the try so a host that parses
        # but cannot be used is reported as a transport failure instead
        # of leaking ``http.client`` internals.
        conn = _get_connection(config["host"])
        conn.request(method, url, body=payload, headers=headers)
        response = conn.getresponse()
        # A non-UTF-8 body must not escape the transport wrapping, so
        # decode leniently and let the response models reject the payload.
        raw_body = response.read().decode("utf-8", errors="replace")
        status = response.status
        reason = response.reason
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise MLflowTransportError(method, path, exc) from exc
    finally:
        if conn is not None:
            conn.close()

    if not 200 <= status < 300:
        raise MLflowAPIError(
            status, reason, _parse_response_body(raw_body), method, path
        )

    return status, reason, _parse_response_body(raw_body)


def _scorer_path(command: str) -> str:
    return f"{API_PATH}/{command}"


def _require_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("scorer name must be a non-empty string")
    return name.strip()


def _require_experiment_id(experiment_id: str) -> str:
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise ValueError("experiment_id must be a non-empty string")
    return experiment_id.strip()


def _validate_version(version: int) -> None:
    if isinstance(version, bool) or not isinstance(version, int):
        raise TypeError("version must be an integer")
    if version < 1:
        raise ValueError("version must be 1 or greater")


def _resolve_experiment_id(
    experiment_id: str | None, config: Mapping[str, str]
) -> str:
    """Resolve the experiment scope of a single-experiment operation.

    Only an omitted or empty ``experiment_id`` falls back to the configured
    default. Any other value reaches ``_require_experiment_id``, so an
    explicit falsy non-string (``0``, ``False``) is rejected instead of
    silently operating on the default experiment.
    """
    if experiment_id is None or experiment_id == "":
        experiment_id = config.get("experiment_id", "")
    return _require_experiment_id(experiment_id)


def register_scorer(scorer: Mapping[str, Any], config: Mapping[str, str]) -> Scorer:
    """Register a scorer and return it with its ``scorer_id`` and version."""
    payload = validate_scorer_payload(scorer, config.get("experiment_id"))
    _, _, body = _request("POST", _scorer_path("register"), config, body=payload)
    return Scorer.from_api(body)


def get_scorer(
    name: str,
    config: Mapping[str, str],
    experiment_id: str | None = None,
    version: int | None = None,
) -> Scorer:
    """Retrieve a scorer, defaulting to its latest version.

    When ``version`` is omitted the parameter is not sent, which asks
    MLflow for the version with the maximum version number.
    """
    name = _require_name(name)
    resolved_experiment_id = _resolve_experiment_id(experiment_id, config)
    if version is not None:
        _validate_version(version)
    _, _, body = _request(
        "GET",
        _scorer_path("get"),
        config,
        query={
            "experiment_id": resolved_experiment_id,
            "name": name,
            "version": version,
        },
    )
    return Scorer.from_api(body)


def list_scorers(
    config: Mapping[str, str],
    experiment_id: str | None = None,
) -> tuple[Scorer, ...]:
    """List an experiment's scorers (latest version of each name).

    The experiment defaults to the configured ``experiment_id`` and can be
    overridden per call. MLflow returns the complete collection in one
    response; there is no page token for this endpoint.
    """
    query = {"experiment_id": _resolve_experiment_id(experiment_id, config)}
    _, _, body = _request("GET", _scorer_path("list"), config, query=query)
    return scorers_from_list(body)


def list_scorer_versions(
    name: str,
    config: Mapping[str, str],
    experiment_id: str | None = None,
) -> tuple[Scorer, ...]:
    """List every version of an experiment's scorer."""
    name = _require_name(name)
    resolved_experiment_id = _resolve_experiment_id(experiment_id, config)
    _, _, body = _request(
        "GET",
        _scorer_path("versions"),
        config,
        query={"experiment_id": resolved_experiment_id, "name": name},
    )
    return scorers_from_list(body)


def delete_scorer(
    name: str,
    config: Mapping[str, str],
    experiment_id: str | None = None,
    version: int | None = None,
) -> None:
    """Delete one scorer version, or every version when omitted."""
    name = _require_name(name)
    resolved_experiment_id = _resolve_experiment_id(experiment_id, config)
    if version is not None:
        _validate_version(version)
    body: dict[str, Any] = {
        "experiment_id": resolved_experiment_id,
        "name": name,
    }
    if version is not None:
        body["version"] = version
    _request("DELETE", _scorer_path("delete"), config, body=body)
