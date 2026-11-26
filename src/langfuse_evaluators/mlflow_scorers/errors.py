"""Error types for the MLflow scorer API.

MLflow reports failures with an HTTP status code plus a machine-readable
``error_code``. The scorer client maps both onto the same stable error
kinds the Langfuse client uses, so callers of either integration branch
on ``error_kind`` instead of parsing message text.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import error_kind_for_status

# MLflow error codes that carry a meaning the HTTP status alone can lose.
# MLflow historically returns 400 for several of these, so the code is the
# more precise signal when both are present.
ERROR_KINDS_BY_CODE = {
    "RESOURCE_ALREADY_EXISTS": "conflict",
    "RESOURCE_DOES_NOT_EXIST": "not_found",
    "ENDPOINT_NOT_FOUND": "not_found",
    "INVALID_PARAMETER_VALUE": "validation_error",
    "INVALID_STATE": "validation_error",
    "PERMISSION_DENIED": "permission_error",
    "UNAUTHENTICATED": "authentication_error",
    "TOO_MANY_REQUESTS": "rate_limit_error",
    "INTERNAL_ERROR": "server_error",
    "TEMPORARILY_UNAVAILABLE": "server_error",
}


def error_kind_for_response(status_code: int, error_code: str | None = None) -> str:
    """Return the stable error kind for a status code and MLflow error code.

    A recognised ``error_code`` wins because MLflow overloads some status
    codes: a duplicate registration and a missing scorer can both arrive
    as HTTP 400 while their error codes distinguish them.
    """
    if error_code is not None:
        kind = ERROR_KINDS_BY_CODE.get(error_code)
        if kind is not None:
            return kind
    return error_kind_for_status(status_code)


class MLflowError(Exception):
    """Base class for all errors raised by the MLflow scorer client."""


class MLflowAPIError(MLflowError):
    """A non-2xx response from the MLflow scorer API.

    ``body`` keeps the structured MLflow error payload, ``error_code``
    keeps its machine-readable code, and ``error_kind`` exposes the
    stable kind shared with the Langfuse client.
    """

    def __init__(
        self,
        status_code: int,
        reason: str,
        body: Any,
        method: str,
        path: str,
    ) -> None:
        self.status_code = int(status_code)
        self.reason = reason or ""
        self.body = dict(body) if isinstance(body, Mapping) else {"message": str(body)}
        raw_code = self.body.get("error_code")
        self.error_code = raw_code if isinstance(raw_code, str) else None
        self.error_kind = error_kind_for_response(self.status_code, self.error_code)
        self.method = method
        self.path = path
        super().__init__(self._describe())

    @property
    def message(self) -> str:
        """The API-provided message, falling back to the HTTP reason."""
        message = self.body.get("message")
        if isinstance(message, str) and message:
            return message
        error = self.body.get("error")
        if isinstance(error, str) and error:
            return error
        return self.reason or f"HTTP {self.status_code}"

    def _describe(self) -> str:
        # Only the status, stable kind, error code, and API-provided
        # message are surfaced. Request headers and payloads are never
        # included.
        code = f" {self.error_code}" if self.error_code else ""
        return (
            f"{self.method} {self.path} failed with "
            f"{self.status_code} {self.reason}{code} "
            f"({self.error_kind}): {self.message}"
        )


class MLflowTransportError(MLflowError):
    """The request never produced an HTTP response."""

    def __init__(self, method: str, path: str, cause: BaseException) -> None:
        self.method = method
        self.path = path
        self.cause = cause
        super().__init__(
            f"Could not reach the MLflow scorer API for {method} {path}; "
            "check MLFLOW_HOST and your network connection "
            f"({cause.__class__.__name__})"
        )


class MLflowResponseError(MLflowError, ValueError):
    """A 2xx response whose payload does not match the expected contract."""
