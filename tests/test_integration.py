"""Integration tests against a real local HTTP server.

The unit tests replace ``http.client`` with a fake, so these tests cover
the one thing a fake cannot: that the client actually speaks HTTP to a
server, builds a valid request, and parses a real response.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest

from langfuse_evaluators import client
from langfuse_evaluators.errors import LangfuseAPIError

PAYLOAD = {
    "name": "JSON Parseable Output",
    "description": "Checks if the observation output is valid JSON",
    "type": "code",
    "sourceCode": "function evaluate() { return {}; }",
    "sourceCodeLanguage": "TYPESCRIPT",
}
API_EVALUATOR = {
    "id": "eval-1",
    "name": "JSON Parseable Output",
    "description": "Checks if the observation output is valid JSON",
    "type": "code",
    "version": 1,
    "createdAt": "2026-01-01T00:00:00Z",
    "updatedAt": "2026-01-01T00:00:00Z",
}


class EvaluatorHandler(BaseHTTPRequestHandler):
    """A tiny Langfuse v2 evaluators stand-in."""

    server_version = "FakeLangfuse/1.0"

    def log_message(self, *args):  # keep pytest output clean
        pass

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, body=None) -> None:
        self.server.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self._record(body)
        created = dict(API_EVALUATOR, name=body.get("name", API_EVALUATOR["name"]))
        self._reply(201, created)

    def do_GET(self) -> None:
        self._record()
        path = urlparse(self.path).path
        if path == client.API_PATH:
            self._reply(200, {"data": [API_EVALUATOR], "meta": {"cursor": "next"}})
        elif path == f"{client.API_PATH}/eval-1":
            self._reply(200, API_EVALUATOR)
        elif path == f"{client.API_PATH}/missing":
            self._reply(404, {"message": "Evaluator not found", "error": "NotFound"})
        else:
            self._reply(404, {"message": "no route"})


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), EvaluatorHandler)
    httpd.requests = []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture
def live_config(server):
    host, port = server.server_address[:2]
    return {
        "host": f"http://{host}:{port}",
        "credentials": base64.b64encode(b"pk-live:sk-live").decode(),
    }


def test_create_get_and_list_against_live_server(server, live_config):
    created = client.create_evaluator(PAYLOAD, live_config)
    assert created.evaluator_id == "eval-1"
    assert created.version == 1

    fetched = client.get_evaluator("eval-1", live_config)
    assert fetched.name == API_EVALUATOR["name"]

    page = client.list_evaluators(live_config, limit=5)
    assert [item.evaluator_id for item in page.data] == ["eval-1"]
    assert page.cursor == "next"

    first = server.requests[0]
    assert first["method"] == "POST"
    assert first["path"] == client.API_PATH
    assert first["authorization"] == f"Basic {live_config['credentials']}"
    assert first["body"]["name"] == PAYLOAD["name"]


def test_live_server_error_maps_to_not_found(live_config):
    with pytest.raises(LangfuseAPIError) as excinfo:
        client.get_evaluator("missing", live_config)

    assert excinfo.value.status_code == 404
    assert excinfo.value.error_kind == "not_found"
    assert excinfo.value.message == "Evaluator not found"
