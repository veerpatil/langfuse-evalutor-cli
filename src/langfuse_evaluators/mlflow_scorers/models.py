"""Request and response models for the MLflow scorer API.

MLflow scorers are scoped to an experiment and addressed by the pair
``(experiment_id, scorer_name)``. Registering a name creates a new
``scorer_version`` under a stable ``scorer_id``. These models keep the
raw payload alongside the typed fields so callers can use either
representation without the client losing forward-compatible fields.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import MLflowResponseError


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _optional_id(value: Any) -> str | None:
    """Return an identifier as a string.

    MLflow's ``Scorer`` protobuf stores ``experiment_id`` as an int64, so
    protobuf JSON can serialise it either as a number or as a string.
    Accept both and normalise to the string the client uses everywhere.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    return _optional_str(value)


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        # ``int`` accepts a leading sign, so a guard like
        # ``lstrip("-").isdigit()`` let values such as ``"--5"`` through
        # and escaped as a plain ``ValueError``. Convert and fall back so a
        # malformed numeric string yields ``None`` like every other
        # unsupported type.
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _optional_timestamp(value: Any) -> int | str | None:
    """Return an epoch-millisecond timestamp or the raw ISO string.

    MLflow reports ``creation_time`` as epoch milliseconds, but keeping a
    string through means a server that returns an ISO-8601 timestamp is
    not silently dropped from the typed field.
    """
    timestamp = _optional_int(value)
    if timestamp is not None:
        return timestamp
    return _optional_str(value)


def _as_mapping(payload: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise MLflowResponseError(
            f"Expected a JSON object for {label}, got {type(payload).__name__}"
        )
    return payload


def validate_scorer_payload(payload: Any, experiment_id: str | None = None) -> dict:
    """Validate and copy a scorer registration payload.

    Returns a plain ``dict`` that can be serialised straight onto the
    wire. ``experiment_id`` may come from the payload or from the
    configured default; every scorer must be bound to an experiment.
    Unknown keys are preserved so newer MLflow fields can be passed
    through without a client release.

    A malformed *request* payload is the caller's error, so it raises
    ``ValueError``. ``MLflowResponseError`` is reserved for a 2xx
    response whose body does not match the contract.

    ``name`` is stripped so registration sends the same wire value that
    ``get``, ``delete``, and ``versions`` send after their own
    normalisation; scorers are addressed by ``(experiment_id, name)``,
    so an unstripped register would not be found by a later lookup.
    """
    if not isinstance(payload, Mapping):
        raise ValueError(
            f"Expected a JSON object for the scorer payload, got "
            f"{type(payload).__name__}"
        )
    data = payload

    # Only an unset value (missing or empty) falls back to the configured
    # default. Any other falsy value (``0``, ``False``) is an explicit
    # experiment id and fails the type check below, instead of silently
    # registering the scorer under a different experiment.
    raw_experiment_id = data.get("experiment_id")
    resolved_experiment_id = (
        raw_experiment_id
        if raw_experiment_id is not None and raw_experiment_id != ""
        else experiment_id
    )
    if (
        not isinstance(resolved_experiment_id, str)
        or not resolved_experiment_id.strip()
    ):
        raise ValueError(
            "Scorer payload requires a non-empty 'experiment_id' or a configured "
            "MLFLOW_EXPERIMENT_ID"
        )

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Scorer payload requires a non-empty 'name'")

    serialized = data.get("serialized_scorer")
    if not isinstance(serialized, str) or not serialized.strip():
        raise ValueError(
            "Scorer payload requires a non-empty string 'serialized_scorer'"
        )

    validated = dict(data)
    validated["experiment_id"] = resolved_experiment_id.strip()
    validated["name"] = name.strip()
    return validated


@dataclass(frozen=True)
class Scorer:
    """A scorer as returned by ``/api/3.0/mlflow/scorers``."""

    scorer_id: str
    name: str = ""
    experiment_id: str | None = None
    serialized_scorer: str | None = None
    version: int | None = None
    creation_time: int | str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: Any) -> Scorer:
        data = _as_mapping(payload, "scorer")
        # A get response wraps the entity under ``scorer``; list and
        # register responses carry it directly.
        if isinstance(data.get("scorer"), Mapping):
            data = data["scorer"]
        scorer_id = _optional_str(data.get("scorer_id"))
        if not scorer_id:
            raise MLflowResponseError(
                "Scorer payload is missing a non-empty string 'scorer_id'"
            )
        return cls(
            scorer_id=scorer_id,
            # Register responses use ``name``/``version``; the Scorer
            # entity used by get and list uses ``scorer_name``/
            # ``scorer_version``.
            name=_optional_str(data.get("scorer_name"))
            or _optional_str(data.get("name"))
            or "",
            experiment_id=_optional_id(data.get("experiment_id")),
            serialized_scorer=_optional_str(data.get("serialized_scorer")),
            version=_optional_int(data.get("scorer_version"))
            if data.get("scorer_version") is not None
            else _optional_int(data.get("version")),
            creation_time=_optional_timestamp(data.get("creation_time")),
            raw=dict(data),
        )

    def to_dict(self) -> dict:
        """Return the API payload for this scorer."""
        return dict(self.raw)


def scorers_from_list(payload: Any) -> tuple[Scorer, ...]:
    """Parse a ``{"scorers": [...]}`` response.

    MLflow omits the repeated ``scorers`` field when the result is empty,
    so a missing key means an empty collection rather than a malformed
    response.
    """
    data = _as_mapping(payload, "scorer list")
    items = data.get("scorers", [])
    if not isinstance(items, list):
        raise MLflowResponseError(
            "Expected a JSON list under 'scorers' for the scorer list"
        )
    return tuple(Scorer.from_api(item) for item in items)
