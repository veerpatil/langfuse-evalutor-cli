"""Tests for the Langfuse v2 evaluators client."""

from __future__ import annotations

import http.client
from urllib.parse import parse_qs, urlparse

import pytest
from helpers import FakeResponse, json_response

from langfuse_evaluators import client
from langfuse_evaluators.errors import (
    LangfuseAPIError,
    LangfuseError,
    LangfuseResponseError,
    LangfuseTransportError,
)

API_PATH = "/api/public/v2/evaluators"
EVALUATOR_PAYLOAD = {
    "name": "JSON Parseable Output",
    "description": "Checks if the observation output is valid JSON",
    "type": "code",
    "sourceCode": "function evaluate() { return {}; }",
    "sourceCodeLanguage": "TYPESCRIPT",
}
API_EVALUATOR = {
    "id": "eval-123",
    "name": "JSON Parseable Output",
    "description": "Checks if the observation output is valid JSON",
    "type": "code",
    "version": 2,
    "createdAt": "2026-01-01T00:00:00Z",
    "updatedAt": "2026-02-01T00:00:00Z",
}


def query_params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def path_of(url: str) -> str:
    return urlparse(url).path


# --- requests -------------------------------------------------------------


def test_create_evaluator_posts_to_v2_endpoint(connection, config):
    conn = connection(json_response(API_EVALUATOR, status=201, reason="Created"))

    evaluator = client.create_evaluator(EVALUATOR_PAYLOAD, config)

    assert len(conn.calls) == 1
    call = conn.calls[0]
    assert call.method == "POST"
    assert path_of(call.url) == API_PATH
    assert query_params(call.url) == {}
    assert call.body == EVALUATOR_PAYLOAD
    assert call.headers["Content-Type"] == "application/json"
    assert call.headers["Authorization"] == f"Basic {config['credentials']}"
    assert conn.closed

    assert evaluator.evaluator_id == "eval-123"
    assert evaluator.version == 2
    assert evaluator.to_dict()["id"] == "eval-123"


def test_get_evaluator_uses_stable_id(connection, config):
    conn = connection(json_response(API_EVALUATOR))

    evaluator = client.get_evaluator("eval-123", config)

    assert conn.calls[0].method == "GET"
    assert path_of(conn.calls[0].url) == f"{API_PATH}/eval-123"
    assert evaluator.name == "JSON Parseable Output"


def test_evaluator_ids_are_url_encoded(connection, config):
    conn = connection(json_response(API_EVALUATOR))

    client.get_evaluator("eval/with spaces", config)

    assert path_of(conn.calls[0].url) == f"{API_PATH}/eval%2Fwith%20spaces"


def test_get_evaluator_rejects_empty_id(config):
    with pytest.raises(ValueError):
        client.get_evaluator("  ", config)


def test_get_evaluator_unwraps_data_envelope(connection, config):
    connection(json_response({"data": API_EVALUATOR}))

    evaluator = client.get_evaluator("eval-123", config)

    assert evaluator.evaluator_id == "eval-123"


def test_update_evaluator_puts_changes(connection, config):
    updated = dict(API_EVALUATOR, version=3)
    conn = connection(json_response(updated))

    evaluator = client.update_evaluator("eval-123", {"description": "new"}, config)

    assert conn.calls[0].method == "PUT"
    assert path_of(conn.calls[0].url) == f"{API_PATH}/eval-123"
    assert conn.calls[0].body == {"description": "new"}
    assert evaluator.version == 3


def test_update_evaluator_requires_changes(connection, config):
    conn = connection()

    with pytest.raises(ValueError):
        client.update_evaluator("eval-123", {}, config)

    assert conn.calls == []


def test_delete_evaluator_accepts_empty_body(connection, config):
    conn = connection(FakeResponse(status=204, reason="No Content", body=""))

    client.delete_evaluator("eval-123", config)

    assert conn.calls[0].method == "DELETE"
    assert path_of(conn.calls[0].url) == f"{API_PATH}/eval-123"
    assert conn.closed


def test_request_honours_base_path_in_host(connection, config):
    conn = connection(json_response({"data": []}))

    client.list_evaluators(dict(config, host="https://example.com/langfuse"))

    assert path_of(conn.calls[0].url) == f"/langfuse{API_PATH}"


def test_list_evaluators_sends_cursor_and_limit(connection, config):
    conn = connection(
        json_response(
            {
                "data": [API_EVALUATOR],
                "meta": {"cursor": "next/page", "totalItems": 3},
            }
        )
    )

    page = client.list_evaluators(config, limit=2, cursor="first/page")

    assert conn.calls[0].method == "GET"
    assert path_of(conn.calls[0].url) == API_PATH
    assert query_params(conn.calls[0].url) == {
        "limit": ["2"],
        "cursor": ["first/page"],
    }
    assert [item.evaluator_id for item in page.data] == ["eval-123"]
    assert page.cursor == "next/page"
    assert page.has_more is True
    assert page.meta["totalItems"] == 3


def test_list_evaluators_omits_empty_cursor(connection, config):
    conn = connection(json_response({"data": [], "meta": {}}))

    page = client.list_evaluators(config)

    assert "cursor" not in query_params(conn.calls[0].url)
    assert page.cursor is None
    assert page.has_more is False


def test_list_evaluators_accepts_bare_list(connection, config):
    connection(json_response([API_EVALUATOR]))

    page = client.list_evaluators(config)

    assert [item.evaluator_id for item in page.data] == ["eval-123"]
    assert page.cursor is None


@pytest.mark.parametrize(
    ("limit", "exception"),
    [
        (0, ValueError),
        (-1, ValueError),
        (101, ValueError),
        (True, TypeError),
        ("10", TypeError),
    ],
)
def test_list_evaluators_rejects_invalid_limit(connection, config, limit, exception):
    conn = connection()

    with pytest.raises(exception):
        client.list_evaluators(config, limit=limit)

    assert conn.calls == []


def test_iter_evaluators_follows_cursors_without_duplicates(connection, config):
    conn = connection(
        json_response(
            {
                "data": [
                    dict(API_EVALUATOR, id="eval-1"),
                    dict(API_EVALUATOR, id="eval-2"),
                ],
                "meta": {"cursor": "cursor-2"},
            }
        ),
        json_response(
            {
                # eval-2 is repeated to prove duplicates are dropped.
                "data": [
                    dict(API_EVALUATOR, id="eval-2"),
                    dict(API_EVALUATOR, id="eval-3"),
                ],
                "meta": {"cursor": "cursor-3"},
            }
        ),
        json_response(
            {
                "data": [dict(API_EVALUATOR, id="eval-4")],
                "meta": {},
            }
        ),
    )

    evaluators = list(client.iter_evaluators(config, limit=2))

    assert [item.evaluator_id for item in evaluators] == [
        "eval-1",
        "eval-2",
        "eval-3",
        "eval-4",
    ]
    assert len(conn.calls) == 3
    assert query_params(conn.calls[0].url) == {"limit": ["2"]}
    assert query_params(conn.calls[1].url) == {
        "limit": ["2"],
        "cursor": ["cursor-2"],
    }
    assert query_params(conn.calls[2].url) == {
        "limit": ["2"],
        "cursor": ["cursor-3"],
    }


def test_iter_evaluators_starts_at_supplied_cursor(connection, config):
    conn = connection(json_response({"data": [API_EVALUATOR], "meta": {}}))

    evaluators = list(client.iter_evaluators(config, limit=5, cursor="resume-here"))

    assert [item.evaluator_id for item in evaluators] == ["eval-123"]
    assert query_params(conn.calls[0].url) == {
        "limit": ["5"],
        "cursor": ["resume-here"],
    }


def test_iter_evaluators_stops_on_repeated_cursor(connection, config):
    conn = connection(
        json_response(
            {
                "data": [dict(API_EVALUATOR, id="eval-1")],
                "meta": {"cursor": "cursor-2"},
            }
        ),
        json_response(
            {
                "data": [dict(API_EVALUATOR, id="eval-2")],
                "meta": {"cursor": "cursor-2"},
            }
        ),
    )

    evaluators = list(client.iter_evaluators(config))

    assert [item.evaluator_id for item in evaluators] == ["eval-1", "eval-2"]
    assert len(conn.calls) == 2


def test_list_evaluator_versions_uses_versions_path(connection, config):
    conn = connection(
        json_response(
            {
                "data": [
                    {"version": 3, "createdAt": "2026-03-01T00:00:00Z"},
                    {"version": 2, "createdAt": "2026-02-01T00:00:00Z"},
                ],
                "meta": {"cursor": "versions-cursor"},
            }
        )
    )

    page = client.list_evaluator_versions("eval-123", config, limit=10)

    assert conn.calls[0].method == "GET"
    assert path_of(conn.calls[0].url) == f"{API_PATH}/eval-123/versions"
    assert query_params(conn.calls[0].url) == {"limit": ["10"]}
    assert [version.version for version in page.data] == [3, 2]
    assert all(version.evaluator_id == "eval-123" for version in page.data)
    assert page.cursor == "versions-cursor"


def test_iter_evaluator_versions_deduplicates(connection, config):
    conn = connection(
        json_response(
            {
                "data": [{"version": 2}, {"version": 1}],
                "meta": {"cursor": "v2-cursor"},
            }
        ),
        json_response({"data": [{"version": 1}, {"version": 3}], "meta": {}}),
    )

    versions = list(client.iter_evaluator_versions("eval-123", config))

    assert [version.version for version in versions] == [2, 1, 3]
    assert len(conn.calls) == 2


# --- errors ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "reason", "kind"),
    [
        (400, "Bad Request", "validation_error"),
        (401, "Unauthorized", "authentication_error"),
        (403, "Forbidden", "permission_error"),
        (404, "Not Found", "not_found"),
        (409, "Conflict", "conflict"),
        (422, "Unprocessable Entity", "validation_error"),
        (429, "Too Many Requests", "rate_limit_error"),
        (500, "Internal Server Error", "server_error"),
        (503, "Service Unavailable", "server_error"),
        (418, "I'm a teapot", "api_error"),
    ],
)
def test_langfuse_errors_are_mapped_by_status(connection, config, status, reason, kind):
    error_body = {
        "message": "Evaluator rejected",
        "error": "EvaluatorError",
        "details": [{"field": "name", "message": "already taken"}],
    }
    connection(json_response(error_body, status=status, reason=reason))

    with pytest.raises(LangfuseAPIError) as excinfo:
        client.create_evaluator(EVALUATOR_PAYLOAD, config)

    error = excinfo.value
    assert error.status_code == status
    assert error.reason == reason
    assert error.error_kind == kind
    assert error.body == error_body
    assert error.message == "Evaluator rejected"


def test_error_kind_ignores_message_text(connection, config):
    connection(
        json_response(
            {"message": "404 this looks like a not found error"},
            status=409,
            reason="Conflict",
        )
    )

    with pytest.raises(LangfuseAPIError) as excinfo:
        client.get_evaluator("eval-123", config)

    assert excinfo.value.error_kind == "conflict"


def test_errors_never_leak_credentials(connection, config):
    connection(
        json_response({"message": "Unauthorized"}, status=401, reason="Unauthorized")
    )

    with pytest.raises(LangfuseAPIError) as excinfo:
        client.get_evaluator("eval-123", config)

    rendered = str(excinfo.value)
    assert config["credentials"] not in rendered
    assert "Authorization" not in rendered


def test_transport_errors_are_wrapped(connection, config):
    connection(OSError("connection refused"))

    with pytest.raises(LangfuseTransportError) as excinfo:
        client.get_evaluator("eval-123", config)

    assert isinstance(excinfo.value.cause, OSError)
    assert "connection refused" in str(excinfo.value)
    assert config["credentials"] not in str(excinfo.value)


def test_http_protocol_errors_are_wrapped(connection, config):
    connection(http.client.BadStatusLine("garbage"))

    with pytest.raises(LangfuseTransportError) as excinfo:
        client.get_evaluator("eval-123", config)

    assert isinstance(excinfo.value.cause, http.client.HTTPException)


def test_non_json_error_body_is_kept_as_message(connection, config):
    connection(FakeResponse(status=502, reason="Bad Gateway", body="<html>oops"))

    with pytest.raises(LangfuseAPIError) as excinfo:
        client.get_evaluator("eval-123", config)

    assert excinfo.value.error_kind == "server_error"
    assert excinfo.value.body == {"message": "<html>oops"}


# --- malformed responses --------------------------------------------------


def test_non_json_success_body_raises_response_error(connection, config):
    connection(FakeResponse(status=200, reason="OK", body="<html>not json</html>"))

    with pytest.raises(LangfuseResponseError):
        client.get_evaluator("eval-123", config)


def test_missing_evaluator_id_raises_response_error(connection, config):
    connection(json_response({"name": "no id here"}))

    with pytest.raises(LangfuseResponseError):
        client.get_evaluator("eval-123", config)


def test_create_without_id_is_a_response_error(connection, config):
    connection(json_response({"name": "no id here"}, status=201, reason="Created"))

    with pytest.raises(LangfuseResponseError):
        client.create_evaluator(EVALUATOR_PAYLOAD, config)


def test_list_with_non_list_data_raises_response_error(connection, config):
    connection(json_response({"data": "not-a-list"}))

    with pytest.raises(LangfuseResponseError):
        client.list_evaluators(config)


def test_list_with_non_object_meta_raises_response_error(connection, config):
    connection(json_response({"data": [], "meta": "not-an-object"}))

    with pytest.raises(LangfuseResponseError):
        client.list_evaluators(config)


def test_version_without_version_number_raises_response_error(connection, config):
    connection(json_response({"data": [{"createdAt": "2026-01-01T00:00:00Z"}]}))

    with pytest.raises(LangfuseResponseError):
        client.list_evaluator_versions("eval-123", config)


# --- legacy CLI entry point ----------------------------------------------


def test_create_evaluators_returns_legacy_keys_with_evaluator_id(
    connection, config, monkeypatch
):
    monkeypatch.setattr(client, "get_config", lambda: config)
    connection(
        json_response(API_EVALUATOR, status=201, reason="Created"),
        json_response(
            {"message": "Forbidden", "error": "AccessDenied"},
            status=403,
            reason="Forbidden",
        ),
    )

    results = client.create_evaluators(
        [EVALUATOR_PAYLOAD, dict(EVALUATOR_PAYLOAD, name="Response Relevance")]
    )

    created, failed = results
    assert created["status"] == 201
    assert created["reason"] == "Created"
    assert created["name"] == "JSON Parseable Output"
    assert created["evaluatorId"] == "eval-123"
    assert created["version"] == 2
    assert created["body"]["id"] == "eval-123"

    assert failed["status"] == 403
    assert failed["name"] == "Response Relevance"
    assert failed["evaluatorId"] is None
    assert failed["version"] is None
    assert failed["body"]["error"] == "AccessDenied"


def test_create_evaluators_reports_invalid_payloads(connection, config, monkeypatch):
    monkeypatch.setattr(client, "get_config", lambda: config)
    conn = connection()

    results = client.create_evaluators([{"name": "Missing type"}])

    assert len(conn.calls) == 0
    assert results[0]["status"] == 0
    assert results[0]["name"] == "Missing type"
    assert "Unsupported evaluator type" in results[0]["body"]["message"]


def test_create_evaluators_reports_transport_failures(connection, config, monkeypatch):
    monkeypatch.setattr(client, "get_config", lambda: config)
    connection(OSError("boom"))

    results = client.create_evaluators([EVALUATOR_PAYLOAD])

    assert results[0]["status"] == 0
    assert results[0]["reason"] == "OSError"
    assert results[0]["body"]["message"] == "boom"


def test_create_evaluators_reports_unserializable_payloads(
    connection, config, monkeypatch
):
    monkeypatch.setattr(client, "get_config", lambda: config)
    conn = connection(json_response(API_EVALUATOR, status=201, reason="Created"))

    results = client.create_evaluators([dict(EVALUATOR_PAYLOAD, passthrough=object())])

    assert len(conn.calls) == 0
    assert results[0]["status"] == 0
    assert results[0]["reason"] == "TypeError"
    assert "not JSON serializable" in results[0]["body"]["message"]


def test_credentials_with_control_characters_are_rejected(connection, config):
    conn = connection()
    unsafe = dict(config, credentials="abc\r\nX-Injected: 1")

    with pytest.raises(LangfuseError) as excinfo:
        client.get_evaluator("eval-123", unsafe)

    assert conn.calls == []
    assert "abc" not in str(excinfo.value)


def test_missing_credentials_are_rejected(connection, config):
    conn = connection()

    with pytest.raises(LangfuseError):
        client.get_evaluator("eval-123", dict(config, credentials=""))

    assert conn.calls == []


# --- connection selection -------------------------------------------------


def test_get_connection_uses_https_for_cloud_hosts():
    conn = client._get_connection("https://cloud.langfuse.com")

    try:
        assert isinstance(conn, http.client.HTTPSConnection)
        assert conn.host == "cloud.langfuse.com"
    finally:
        conn.close()


def test_get_connection_preserves_environment_base_url():
    conn = client._get_connection("http://langfuse.local:3000/langfuse")

    try:
        assert isinstance(conn, http.client.HTTPConnection)
        assert conn.host == "langfuse.local"
        assert conn.port == 3000
    finally:
        conn.close()
