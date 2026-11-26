"""Tests for the MLflow scorer client."""

from __future__ import annotations

import http.client
from urllib.parse import parse_qs, urlparse

import pytest
from helpers import FakeResponse, json_response

from langfuse_evaluators.mlflow_scorers import client
from langfuse_evaluators.mlflow_scorers.errors import (
    MLflowAPIError,
    MLflowError,
    MLflowResponseError,
    MLflowTransportError,
)

API_PATH = "/api/3.0/mlflow/scorers"
SCORER_PAYLOAD = {
    "name": "Helpfulness",
    "serialized_scorer": '{"name": "Helpfulness", "type": "llm"}',
}
SCORER_ENTITY = {
    "scorer_id": "scorer-1",
    "experiment_id": "exp-1",
    "scorer_name": "Helpfulness",
    "scorer_version": 2,
    "serialized_scorer": '{"name": "Helpfulness", "type": "llm"}',
    "creation_time": 1767225600000,
}


def query_params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def path_of(url: str) -> str:
    return urlparse(url).path


# --- requests -------------------------------------------------------------


def test_register_scorer_posts_json_to_register(mlflow_connection, mlflow_config):
    conn = mlflow_connection(json_response(SCORER_ENTITY, status=201))

    scorer = client.register_scorer(SCORER_PAYLOAD, mlflow_config)

    assert len(conn.calls) == 1
    call = conn.calls[0]
    assert call.method == "POST"
    assert path_of(call.url) == f"{API_PATH}/register"
    assert query_params(call.url) == {}
    assert call.body == {**SCORER_PAYLOAD, "experiment_id": "exp-1"}
    assert call.headers["Content-Type"] == "application/json"
    assert "Authorization" not in call.headers
    assert conn.closed

    assert scorer.scorer_id == "scorer-1"
    assert scorer.version == 2
    assert scorer.experiment_id == "exp-1"


def test_register_scorer_keeps_an_explicit_experiment_id(
    mlflow_connection, mlflow_config
):
    conn = mlflow_connection(json_response(SCORER_ENTITY, status=201))

    client.register_scorer(
        dict(SCORER_PAYLOAD, experiment_id="exp-explicit"), mlflow_config
    )

    assert conn.calls[0].body["experiment_id"] == "exp-explicit"


def test_register_scorer_requires_an_experiment(mlflow_connection, mlflow_config):
    conn = mlflow_connection()

    with pytest.raises(ValueError):
        client.register_scorer(SCORER_PAYLOAD, dict(mlflow_config, experiment_id=""))

    assert conn.calls == []


def test_register_scorer_rejects_a_payload_without_a_serialized_scorer(
    mlflow_connection, mlflow_config
):
    conn = mlflow_connection()

    with pytest.raises(ValueError):
        client.register_scorer({"name": "Missing definition"}, mlflow_config)

    assert conn.calls == []


def test_get_scorer_omits_version_to_resolve_the_latest(
    mlflow_connection, mlflow_config
):
    conn = mlflow_connection(json_response({"scorer": SCORER_ENTITY}))

    scorer = client.get_scorer("Helpfulness", mlflow_config)

    assert conn.calls[0].method == "GET"
    assert path_of(conn.calls[0].url) == f"{API_PATH}/get"
    assert query_params(conn.calls[0].url) == {
        "experiment_id": ["exp-1"],
        "name": ["Helpfulness"],
    }
    assert scorer.version == 2


def test_get_scorer_sends_an_explicit_version_and_experiment(
    mlflow_connection, mlflow_config
):
    conn = mlflow_connection(
        json_response({"scorer": dict(SCORER_ENTITY, scorer_version=1)})
    )

    scorer = client.get_scorer(
        "Helpfulness", mlflow_config, experiment_id="exp-9", version=1
    )

    assert query_params(conn.calls[0].url) == {
        "experiment_id": ["exp-9"],
        "name": ["Helpfulness"],
        "version": ["1"],
    }
    assert scorer.version == 1


def test_get_scorer_rejects_an_empty_name(mlflow_config):
    with pytest.raises(ValueError):
        client.get_scorer("  ", mlflow_config)


@pytest.mark.parametrize(
    ("version", "exception"),
    [
        (0, ValueError),
        (-1, ValueError),
        (True, TypeError),
        ("1", TypeError),
        (1.5, TypeError),
    ],
)
def test_get_scorer_rejects_invalid_versions(
    mlflow_connection, mlflow_config, version, exception
):
    conn = mlflow_connection()

    with pytest.raises(exception):
        client.get_scorer("Helpfulness", mlflow_config, version=version)

    assert conn.calls == []


def test_list_scorers_sends_the_experiment_scope(mlflow_connection, mlflow_config):
    conn = mlflow_connection(
        json_response({"scorers": [SCORER_ENTITY]})
    )

    scorers = client.list_scorers(mlflow_config)

    assert conn.calls[0].method == "GET"
    assert path_of(conn.calls[0].url) == f"{API_PATH}/list"
    assert query_params(conn.calls[0].url) == {"experiment_id": ["exp-1"]}
    assert [scorer.scorer_id for scorer in scorers] == ["scorer-1"]


def test_list_scorers_accepts_an_explicit_experiment(mlflow_connection, mlflow_config):
    conn = mlflow_connection(json_response({"scorers": []}))

    client.list_scorers(mlflow_config, experiment_id="exp-9")

    assert query_params(conn.calls[0].url)["experiment_id"] == ["exp-9"]


def test_request_sends_a_bearer_token_when_configured(
    mlflow_connection, mlflow_config
):
    conn = mlflow_connection(json_response({"scorers": []}))

    client.list_scorers(dict(mlflow_config, authorization="Bearer token-123"))

    assert conn.calls[0].headers["Authorization"] == "Bearer token-123"


def test_request_sends_basic_credentials_when_configured(
    mlflow_connection, mlflow_config
):
    conn = mlflow_connection(json_response({"scorers": []}))

    client.list_scorers(dict(mlflow_config, authorization="Basic dXNlcjpwYXNz"))

    assert conn.calls[0].headers["Authorization"] == "Basic dXNlcjpwYXNz"


def test_list_scorers_supports_a_multi_experiment_filter(
    mlflow_connection, mlflow_config
):
    conn = mlflow_connection(json_response({"scorers": []}))

    client.list_scorers(mlflow_config, experiment_ids=["exp-1", "exp-2"])

    assert query_params(conn.calls[0].url) == {
        "experiment_ids": ["exp-1", "exp-2"]
    }


def test_list_scorers_rejects_both_experiment_scopes(
    mlflow_connection, mlflow_config
):
    conn = mlflow_connection()

    with pytest.raises(ValueError):
        client.list_scorers(
            mlflow_config, experiment_id="exp-1", experiment_ids=["exp-2"]
        )

    assert conn.calls == []


def test_list_scorers_requires_an_experiment(mlflow_connection, mlflow_config):
    conn = mlflow_connection()

    with pytest.raises(ValueError):
        client.list_scorers(dict(mlflow_config, experiment_id=""))

    assert conn.calls == []


def test_list_scorers_rejects_an_empty_experiment_ids_filter(
    mlflow_connection, mlflow_config
):
    conn = mlflow_connection()

    with pytest.raises(ValueError):
        client.list_scorers(mlflow_config, experiment_ids=[])

    assert conn.calls == []


def test_list_scorers_rejects_a_string_for_experiment_ids(
    mlflow_connection, mlflow_config
):
    conn = mlflow_connection()

    with pytest.raises(TypeError):
        client.list_scorers(mlflow_config, experiment_ids="exp-1")

    assert conn.calls == []


def test_list_scorer_versions_uses_the_versions_path(mlflow_connection, mlflow_config):
    conn = mlflow_connection(
        json_response(
            {
                "scorers": [
                    dict(SCORER_ENTITY, scorer_version=2),
                    dict(SCORER_ENTITY, scorer_version=1),
                ]
            }
        )
    )

    versions = client.list_scorer_versions("Helpfulness", mlflow_config)

    assert conn.calls[0].method == "GET"
    assert path_of(conn.calls[0].url) == f"{API_PATH}/versions"
    assert query_params(conn.calls[0].url) == {
        "experiment_id": ["exp-1"],
        "name": ["Helpfulness"],
    }
    assert [version.version for version in versions] == [2, 1]
    assert all(version.scorer_id == "scorer-1" for version in versions)


def test_list_scorer_versions_rejects_an_empty_name(mlflow_config):
    with pytest.raises(ValueError):
        client.list_scorer_versions("  ", mlflow_config)


def test_delete_scorer_omits_version_to_delete_every_version(
    mlflow_connection, mlflow_config
):
    conn = mlflow_connection(FakeResponse(status=200, reason="OK", body="{}"))

    client.delete_scorer("Helpfulness", mlflow_config)

    assert conn.calls[0].method == "DELETE"
    assert path_of(conn.calls[0].url) == f"{API_PATH}/delete"
    assert conn.calls[0].body == {
        "experiment_id": "exp-1",
        "name": "Helpfulness",
    }
    assert conn.calls[0].headers["Content-Type"] == "application/json"
    assert conn.closed


def test_delete_scorer_sends_an_explicit_version(mlflow_connection, mlflow_config):
    conn = mlflow_connection(FakeResponse(status=200, reason="OK", body="{}"))

    client.delete_scorer("Helpfulness", mlflow_config, version=2)

    assert conn.calls[0].body == {
        "experiment_id": "exp-1",
        "name": "Helpfulness",
        "version": 2,
    }


def test_delete_scorer_rejects_an_invalid_version(mlflow_connection, mlflow_config):
    conn = mlflow_connection()

    with pytest.raises(ValueError):
        client.delete_scorer("Helpfulness", mlflow_config, version=0)

    assert conn.calls == []


# --- errors ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "reason", "kind"),
    [
        (400, "Bad Request", "validation_error"),
        (401, "Unauthorized", "authentication_error"),
        (403, "Forbidden", "permission_error"),
        (404, "Not Found", "not_found"),
        (409, "Conflict", "conflict"),
        (429, "Too Many Requests", "rate_limit_error"),
        (500, "Internal Server Error", "server_error"),
        (418, "I'm a teapot", "api_error"),
    ],
)
def test_mlflow_errors_are_mapped_by_status(
    mlflow_connection, mlflow_config, status, reason, kind
):
    error_body = {"error_code": "SOMETHING_ELSE", "message": "Scorer rejected"}
    mlflow_connection(json_response(error_body, status=status, reason=reason))

    with pytest.raises(MLflowAPIError) as excinfo:
        client.get_scorer("Helpfulness", mlflow_config)

    error = excinfo.value
    assert error.status_code == status
    assert error.reason == reason
    assert error.error_kind == kind
    assert error.body == error_body
    assert error.message == "Scorer rejected"


@pytest.mark.parametrize(
    ("error_code", "kind"),
    [
        ("RESOURCE_ALREADY_EXISTS", "conflict"),
        ("RESOURCE_DOES_NOT_EXIST", "not_found"),
        ("INVALID_PARAMETER_VALUE", "validation_error"),
        ("PERMISSION_DENIED", "permission_error"),
        ("INTERNAL_ERROR", "server_error"),
    ],
)
def test_mlflow_error_codes_override_the_status_mapping(
    mlflow_connection, mlflow_config, error_code, kind
):
    # MLflow returns 400 for several of these, so the code is the precise
    # signal for a duplicate registration or a missing scorer.
    mlflow_connection(
        json_response(
            {"error_code": error_code, "message": "rejected"},
            status=400,
            reason="Bad Request",
        )
    )

    with pytest.raises(MLflowAPIError) as excinfo:
        client.register_scorer(SCORER_PAYLOAD, mlflow_config)

    assert excinfo.value.error_code == error_code
    assert excinfo.value.error_kind == kind


def test_error_kind_ignores_message_text(mlflow_connection, mlflow_config):
    mlflow_connection(
        json_response(
            {"message": "404 this looks like a not found error"},
            status=409,
            reason="Conflict",
        )
    )

    with pytest.raises(MLflowAPIError) as excinfo:
        client.get_scorer("Helpfulness", mlflow_config)

    assert excinfo.value.error_kind == "conflict"


def test_transport_errors_are_wrapped(mlflow_connection, mlflow_config):
    mlflow_connection(OSError("connection refused"))

    with pytest.raises(MLflowTransportError) as excinfo:
        client.get_scorer("Helpfulness", mlflow_config)

    assert isinstance(excinfo.value.cause, OSError)
    assert "Could not reach the MLflow scorer API" in str(excinfo.value)


def test_http_protocol_errors_are_wrapped(mlflow_connection, mlflow_config):
    mlflow_connection(http.client.BadStatusLine("garbage"))

    with pytest.raises(MLflowTransportError) as excinfo:
        client.get_scorer("Helpfulness", mlflow_config)

    assert isinstance(excinfo.value.cause, http.client.HTTPException)


def test_non_json_error_body_is_kept_as_message(mlflow_connection, mlflow_config):
    mlflow_connection(FakeResponse(status=502, reason="Bad Gateway", body="<html>oops"))

    with pytest.raises(MLflowAPIError) as excinfo:
        client.get_scorer("Helpfulness", mlflow_config)

    assert excinfo.value.error_kind == "server_error"
    assert excinfo.value.body == {"message": "<html>oops"}


def test_non_utf8_body_is_decoded_instead_of_escaping(
    mlflow_connection, mlflow_config
):
    mlflow_connection(FakeResponse(status=502, reason="Bad Gateway", body=b"\xff\xfe"))

    with pytest.raises(MLflowAPIError) as excinfo:
        client.get_scorer("Helpfulness", mlflow_config)

    assert excinfo.value.status_code == 502
    assert "\ufffd" in excinfo.value.body["message"]


# --- malformed responses --------------------------------------------------


def test_non_json_success_body_raises_response_error(
    mlflow_connection, mlflow_config
):
    mlflow_connection(
        FakeResponse(status=200, reason="OK", body="<html>not json</html>")
    )

    with pytest.raises(MLflowResponseError):
        client.get_scorer("Helpfulness", mlflow_config)


def test_missing_scorer_id_raises_response_error(mlflow_connection, mlflow_config):
    mlflow_connection(json_response({"scorer": {"scorer_name": "no id here"}}))

    with pytest.raises(MLflowResponseError):
        client.get_scorer("Helpfulness", mlflow_config)


def test_list_with_non_object_payload_raises_response_error(
    mlflow_connection, mlflow_config
):
    mlflow_connection(json_response("not-an-object"))

    with pytest.raises(MLflowResponseError):
        client.list_scorers(mlflow_config)


# --- host handling --------------------------------------------------------


def test_request_honours_base_path_in_host(mlflow_connection, mlflow_config):
    conn = mlflow_connection(json_response({"scorers": []}))

    client.list_scorers(dict(mlflow_config, host="https://example.com/mlflow"))

    assert path_of(conn.calls[0].url) == f"/mlflow{API_PATH}/list"


def test_schemeless_host_is_rejected_before_the_request(
    mlflow_connection, mlflow_config
):
    conn = mlflow_connection()

    with pytest.raises(MLflowError) as excinfo:
        client.list_scorers(dict(mlflow_config, host="example.com"))

    assert conn.calls == []
    assert "http:// or https://" in str(excinfo.value)


def test_parse_host_rejects_embedded_credentials():
    with pytest.raises(MLflowError):
        client._parse_host("https://user:pass@example.com")


def test_parse_host_rejects_non_numeric_port():
    with pytest.raises(MLflowError):
        client._parse_host("https://example.com:not-a-port")


def test_parse_host_rejects_query_and_fragment():
    with pytest.raises(MLflowError):
        client._parse_host("https://example.com/mlflow?region=eu")


def test_get_connection_uses_https_for_remote_hosts():
    conn = client._get_connection("https://mlflow.example.com")

    try:
        assert isinstance(conn, http.client.HTTPSConnection)
        assert conn.host == "mlflow.example.com"
    finally:
        conn.close()
