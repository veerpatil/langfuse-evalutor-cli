"""Error types for the Langfuse v2 evaluators API.

Langfuse returns machine-readable error bodies. The client maps HTTP
status codes onto stable error kinds so callers never have to inspect
error message strings to tell an authentication failure from a missing
evaluator or a conflict.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Status codes whose meaning is stable across the Langfuse API. Any other
# 4xx is reported as "api_error" and any 5xx as "server_error".
ERROR_KINDS_BY_STATUS = {
    400: "validation_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limit_error",
}


def error_kind_for_status(status_code: int) -> str:
    """Return the stable error kind for an HTTP status code."""
    kind = ERROR_KINDS_BY_STATUS.get(status_code)
    if kind is not None:
        return kind
    if 500 <= status_code < 600:
        return "server_error"
    return "api_error"


class LangfuseError(Exception):
    """Base class for all errors raised by this client."""


class LangfuseAPIError(LangfuseError):
    """A non-2xx response from the Langfuse API.

    ``body`` keeps the structured error payload returned by Langfuse so
    callers can branch on ``error_kind`` and on fields such as ``error``
    or ``details`` instead of parsing message text.
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
        self.error_kind = error_kind_for_status(self.status_code)
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
        # Only the status, the stable kind and the API-provided message are
        # surfaced. Request headers (which carry credentials) and request
        # payloads are never included.
        return (
            f"{self.method} {self.path} failed with "
            f"{self.status_code} {self.reason} "
            f"({self.error_kind}): {self.message}"
        )

    def to_result(self) -> dict:
        """Return the legacy CLI result shape for this error."""
        return {
            "status": self.status_code,
            "reason": self.reason,
            "body": dict(self.body),
        }


class LangfuseTransportError(LangfuseError):
    """The request never produced an HTTP response."""

    def __init__(self, method: str, path: str, cause: BaseException) -> None:
        self.method = method
        self.path = path
        self.cause = cause
        super().__init__(
            f"Could not reach the Langfuse API for {method} {path}; "
            "check LANGFUSE_HOST and your network connection "
            f"({cause.__class__.__name__})"
        )


class LangfuseResponseError(LangfuseError, ValueError):
    """A 2xx response whose payload does not match the v2 contract."""
