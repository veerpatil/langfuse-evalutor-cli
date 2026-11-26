"""Tests for the v2 request/response models."""

from __future__ import annotations

import pytest

from langfuse_evaluators.errors import LangfuseResponseError
from langfuse_evaluators.models import (
    Evaluator,
    EvaluatorPage,
    EvaluatorVersion,
    EvaluatorVersionPage,
    validate_evaluator_payload,
)

LLM_PAYLOAD = {
    "name": "Response Relevance",
    "description": "Checks relevance",
    "type": "llm_as_judge",
    "prompt": "Is it relevant?",
    "outputDefinition": {"dataType": "BOOLEAN"},
}


def test_validate_returns_a_copy_and_keeps_unknown_fields():
    payload = dict(LLM_PAYLOAD, extraV2Field={"nested": True})

    validated = validate_evaluator_payload(payload)

    assert validated == payload
    assert validated is not payload


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "", "type": "code"},
        {"name": "x", "type": "unknown_type"},
        {"name": "x", "type": "llm_as_judge", "outputDefinition": {}},
        {"name": "x", "type": "code", "sourceCode": ""},
        {"name": "x", "type": "code", "sourceCode": "code"},
        "not-a-mapping",
        None,
    ],
)
def test_validate_rejects_unsupported_payloads(payload):
    with pytest.raises(ValueError):
        validate_evaluator_payload(payload)


def test_evaluator_from_api_reads_v2_fields():
    evaluator = Evaluator.from_api(
        {
            "id": "eval-1",
            "name": "JSON Parseable Output",
            "description": "desc",
            "type": "code",
            "version": "3",
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-02-01T00:00:00Z",
            "futureField": "kept",
        }
    )

    assert evaluator.evaluator_id == "eval-1"
    assert evaluator.name == "JSON Parseable Output"
    assert evaluator.description == "desc"
    assert evaluator.type == "code"
    assert evaluator.version == 3
    assert evaluator.created_at == "2026-01-01T00:00:00Z"
    assert evaluator.updated_at == "2026-02-01T00:00:00Z"
    assert evaluator.to_dict()["futureField"] == "kept"


def test_evaluator_from_api_accepts_evaluator_id_alias():
    evaluator = Evaluator.from_api({"evaluatorId": "eval-2", "name": "Alias"})

    assert evaluator.evaluator_id == "eval-2"
    assert evaluator.version is None


@pytest.mark.parametrize("payload", [{}, {"id": ""}, {"id": 4}, ["id"], "id"])
def test_evaluator_from_api_rejects_malformed_payloads(payload):
    with pytest.raises(LangfuseResponseError):
        Evaluator.from_api(payload)


def test_evaluator_version_defaults_to_requested_id():
    version = EvaluatorVersion.from_api({"version": 2}, "eval-9")

    assert version.evaluator_id == "eval-9"
    assert version.version == 2


def test_evaluator_version_requires_version_number():
    with pytest.raises(LangfuseResponseError):
        EvaluatorVersion.from_api({"version": "latest"})


def test_evaluator_page_reads_cursor_from_meta():
    page = EvaluatorPage.from_api(
        {
            "data": [{"id": "eval-1", "name": "One"}],
            "meta": {"cursor": "next"},
        }
    )

    assert page.has_more is True
    assert page.cursor == "next"
    assert page.data[0].evaluator_id == "eval-1"


def test_evaluator_version_page_passes_through_evaluator_id():
    page = EvaluatorVersionPage.from_api(
        {"data": [{"version": 1}], "meta": {}}, "eval-7"
    )

    assert page.has_more is False
    assert page.data[0].evaluator_id == "eval-7"
