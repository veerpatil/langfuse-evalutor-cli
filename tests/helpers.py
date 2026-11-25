"""Test doubles for the stdlib ``http.client`` layer used by the client."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Call:
    """A recorded HTTP request."""

    method: str
    url: str
    body: Any = None
    headers: dict = field(default_factory=dict)


class FakeResponse:
    """Minimal stand-in for ``http.client.HTTPResponse``."""

    def __init__(self, status: int = 200, reason: str = "OK", body: Any = ""):
        self.status = status
        self.reason = reason
        if isinstance(body, bytes):
            self._body = body
        elif isinstance(body, str):
            self._body = body.encode()
        else:
            self._body = json.dumps(body).encode()

    def read(self) -> bytes:
        return self._body


class FakeConnection:
    """Records requests and returns queued responses in order.

    Queue an exception instance to simulate a transport failure.
    """

    def __init__(self, responses: list[Any]):
        self._responses = list(responses)
        self.calls: list[Call] = []
        self.closed = False
        self._pending: FakeResponse | None = None

    def request(self, method, url, body=None, headers=None):
        parsed_body = json.loads(body) if isinstance(body, str) else body
        self.calls.append(
            Call(
                method=method,
                url=url,
                body=parsed_body,
                headers=dict(headers or {}),
            )
        )
        if not self._responses:
            raise AssertionError("unexpected request: no response queued")
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        self._pending = response

    def getresponse(self) -> FakeResponse:
        assert self._pending is not None, "getresponse called before request"
        return self._pending

    def close(self):
        self.closed = True


def json_response(payload: Any, status: int = 200, reason: str = "OK"):
    """Build a JSON ``FakeResponse`` for ``payload``."""
    return FakeResponse(status=status, reason=reason, body=json.dumps(payload))
