"""Tests for the MLflow scorer request/response models."""

from __future__ import annotations

import pytest

from langfuse_evaluators.mlflow_scorers.errors import MLflowResponseError
from langfuse_evaluators.mlflow_scorers.models import (
    Scorer,
    scorers_from_list,
    validate_scorer_payload,
)

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


def test_validate_returns_a_copy_and_keeps_unknown_fields():
    payload = dict(
        SCORER_PAYLOAD,
        experiment_id="exp-9",
        futureField={"nested": True},
    )

    validated = validate_scorer_payload(payload)

    assert validated == payload
    assert validated is not payload


def test_validate_uses_the_default_experiment_id():
    validated = validate_scorer_payload(SCORER_PAYLOAD, "exp-default")

    assert validated["experiment_id"] == "exp-default"


def test_validate_prefers_the_payload_experiment_id():
    validated = validate_scorer_payload(
        dict(SCORER_PAYLOAD, experiment_id="exp-payload"), "exp-default"
    )

    assert validated["experiment_id"] == "exp-payload"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "", "serialized_scorer": "{}", "experiment_id": "exp"},
        {"name": "n", "serialized_scorer": "", "experiment_id": "exp"},
        {"name": "n", "serialized_scorer": {}, "experiment_id": "exp"},
        {"experiment_id": "exp", "serialized_scorer": "{}"},
        "not-a-mapping",
        None,
    ],
)
def test_validate_rejects_unsupported_payloads(payload):
    with pytest.raises(ValueError):
        validate_scorer_payload(payload, "exp-default")


def test_validate_requires_an_experiment_id():
    with pytest.raises(ValueError) as excinfo:
        validate_scorer_payload(SCORER_PAYLOAD)

    assert "experiment_id" in str(excinfo.value)


@pytest.mark.parametrize("experiment_id", [0, False, 123, []])
def test_validate_rejects_a_non_string_experiment_id(experiment_id):
    # A falsy but explicit experiment id must not be replaced by the
    # configured default, which would register the scorer elsewhere.
    with pytest.raises(ValueError):
        validate_scorer_payload(
            dict(SCORER_PAYLOAD, experiment_id=experiment_id), "exp-default"
        )


def test_validate_treats_an_empty_experiment_id_as_unset():
    validated = validate_scorer_payload(
        dict(SCORER_PAYLOAD, experiment_id=""), "exp-default"
    )

    assert validated["experiment_id"] == "exp-default"


def test_validate_strips_the_name_so_register_and_lookup_agree():
    validated = validate_scorer_payload(
        dict(SCORER_PAYLOAD, name="  Helpfulness  "), "exp-default"
    )

    assert validated["name"] == "Helpfulness"


def test_validate_rejects_a_non_mapping_payload_as_a_request_error():
    # A malformed request payload is the caller's error, so it must not be
    # reported as a bad 2xx response body.
    with pytest.raises(ValueError) as excinfo:
        validate_scorer_payload(["not-a-mapping"], "exp-default")

    assert not isinstance(excinfo.value, MLflowResponseError)


def test_scorer_from_api_reads_the_scorer_entity_fields():
    scorer = Scorer.from_api(dict(SCORER_ENTITY, futureField="kept"))

    assert scorer.scorer_id == "scorer-1"
    assert scorer.experiment_id == "exp-1"
    assert scorer.name == "Helpfulness"
    assert scorer.serialized_scorer == SCORER_ENTITY["serialized_scorer"]
    assert scorer.version == 2
    assert scorer.creation_time == 1767225600000
    assert scorer.to_dict()["futureField"] == "kept"


def test_scorer_from_api_reads_the_register_response_fields():
    scorer = Scorer.from_api(
        {
            "scorer_id": "scorer-1",
            "experiment_id": "exp-1",
            "name": "Helpfulness",
            "version": "3",
            "serialized_scorer": "{}",
            "creation_time": 1767225600000,
        }
    )

    assert scorer.name == "Helpfulness"
    assert scorer.version == 3


def test_scorer_from_api_accepts_a_numeric_experiment_id():
    scorer = Scorer.from_api(dict(SCORER_ENTITY, experiment_id=12))

    assert scorer.experiment_id == "12"


def test_scorer_from_api_unwraps_a_get_response():
    scorer = Scorer.from_api({"scorer": SCORER_ENTITY})

    assert scorer.scorer_id == "scorer-1"


def test_scorer_from_api_accepts_an_iso_creation_time():
    scorer = Scorer.from_api(
        dict(SCORER_ENTITY, creation_time="2026-01-01T00:00:00Z")
    )

    assert scorer.creation_time == "2026-01-01T00:00:00Z"


@pytest.mark.parametrize("version", ["--5", "5.0", "++5", "", "  "])
def test_scorer_from_api_ignores_a_malformed_numeric_version(version):
    # A malformed numeric string must not escape as a plain ValueError from
    # the response parser.
    scorer = Scorer.from_api(dict(SCORER_ENTITY, scorer_version=version))

    assert scorer.version is None


def test_scorer_from_api_accepts_a_signed_numeric_version():
    scorer = Scorer.from_api(dict(SCORER_ENTITY, scorer_version=" -2 "))

    assert scorer.version == -2


@pytest.mark.parametrize(
    "payload",
    [{}, {"scorer_id": ""}, {"scorer_id": 4}, ["scorer_id"], "scorer_id"],
)
def test_scorer_from_api_rejects_malformed_payloads(payload):
    with pytest.raises(MLflowResponseError):
        Scorer.from_api(payload)


def test_scorers_from_list_reads_the_collection():
    scorers = scorers_from_list(
        {"scorers": [SCORER_ENTITY, dict(SCORER_ENTITY, scorer_version=1)]}
    )

    assert [scorer.version for scorer in scorers] == [2, 1]
    assert all(scorer.scorer_id == "scorer-1" for scorer in scorers)


def test_scorers_from_list_treats_a_missing_collection_as_empty():
    assert scorers_from_list({}) == ()


def test_scorers_from_list_rejects_non_list_scorers():
    with pytest.raises(MLflowResponseError):
        scorers_from_list({"scorers": "not-a-list"})
