"""Request and response models for the Langfuse v2 evaluators API.

The v2 API identifies evaluators by a stable ``evaluatorId`` and tracks
each change as a numbered revision. These models keep the raw payload
alongside the typed fields so callers can use either representation
without the client losing forward-compatible fields.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import LangfuseResponseError

LLM_AS_JUDGE = "llm_as_judge"
CODE = "code"
SUPPORTED_EVALUATOR_TYPES = (LLM_AS_JUDGE, CODE)

# Fields the v2 create/update contract requires for each supported type.
REQUIRED_FIELDS_BY_TYPE = {
    LLM_AS_JUDGE: ("name", "prompt", "outputDefinition"),
    CODE: ("name", "sourceCode", "sourceCodeLanguage"),
}


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.lstrip("-").isdigit():
            return int(candidate)
    return None


def _as_mapping(payload: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise LangfuseResponseError(
            f"Expected a JSON object for {label}, got {type(payload).__name__}"
        )
    return payload


def validate_evaluator_payload(payload: Any) -> dict:
    """Validate and copy an evaluator create payload.

    Returns a plain ``dict`` that can be serialised straight onto the
    wire. Unknown keys are preserved so newer v2 fields can be passed
    through without a client release.
    """
    data = _as_mapping(payload, "evaluator")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Evaluator payload requires a non-empty 'name'")

    evaluator_type = data.get("type")
    if evaluator_type not in SUPPORTED_EVALUATOR_TYPES:
        supported = ", ".join(SUPPORTED_EVALUATOR_TYPES)
        raise ValueError(
            f"Unsupported evaluator type {evaluator_type!r}; supported types: "
            f"{supported}"
        )

    for required in REQUIRED_FIELDS_BY_TYPE[evaluator_type]:
        value = data.get(required)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(
                f"Evaluator payload of type {evaluator_type!r} requires '{required}'"
            )

    return dict(data)


@dataclass(frozen=True)
class Evaluator:
    """An evaluator as returned by ``/api/public/v2/evaluators``."""

    evaluator_id: str
    name: str
    description: str | None = None
    type: str | None = None
    version: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: Any) -> Evaluator:
        data = _as_mapping(payload, "evaluator")
        # Both keys are accepted until the live v2 contract is confirmed;
        # see the note on ``_unwrap_object`` in client.py.
        # TODO(#2): pin to the documented key and remove the fallback once
        # verified against a live v2 instance.
        evaluator_id = data.get("id") or data.get("evaluatorId")
        if not isinstance(evaluator_id, str) or not evaluator_id:
            raise LangfuseResponseError(
                "Evaluator payload is missing a non-empty string 'id'"
            )
        return cls(
            evaluator_id=evaluator_id,
            name=_optional_str(data.get("name")) or "",
            description=_optional_str(data.get("description")),
            type=_optional_str(data.get("type")),
            version=_optional_int(data.get("version")),
            created_at=_optional_str(data.get("createdAt")),
            updated_at=_optional_str(data.get("updatedAt")),
            raw=dict(data),
        )

    def to_dict(self) -> dict:
        """Return the API payload for this evaluator."""
        return dict(self.raw)


@dataclass(frozen=True)
class EvaluatorVersion:
    """A single revision in an evaluator's version history."""

    evaluator_id: str
    version: int
    created_at: str | None = None
    updated_at: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: Any, evaluator_id: str = "") -> EvaluatorVersion:
        data = _as_mapping(payload, "evaluator version")
        version = _optional_int(data.get("version"))
        if version is None:
            raise LangfuseResponseError(
                "Evaluator version payload is missing an integer 'version'"
            )
        # Only an explicit ``evaluatorId`` is trusted here: a version row's
        # own ``id`` is the id of that row, not of the evaluator it belongs
        # to, so falling back to it would silently mislabel a version.
        payload_id = _optional_str(data.get("evaluatorId"))
        return cls(
            evaluator_id=_optional_str(payload_id) or evaluator_id,
            version=version,
            created_at=_optional_str(data.get("createdAt")),
            updated_at=_optional_str(data.get("updatedAt")),
            raw=dict(data),
        )

    def to_dict(self) -> dict:
        """Return the API payload for this evaluator version."""
        return dict(self.raw)


def _page_from_api(
    payload: Any,
    label: str,
    factory: Callable[[Any], Any],
) -> tuple[tuple[Any, ...], str | None, Mapping[str, Any]]:
    if isinstance(payload, list):
        items: Any = payload
        meta: Mapping[str, Any] = {}
    elif isinstance(payload, Mapping):
        items = payload.get("data")
        raw_meta = payload.get("meta")
        if raw_meta is None:
            raw_meta = {}
        if not isinstance(raw_meta, Mapping):
            raise LangfuseResponseError(
                f"Expected the {label} list 'meta' field to be a JSON object"
            )
        meta = raw_meta
    else:
        raise LangfuseResponseError(
            f"Expected a JSON object for the {label} list, got {type(payload).__name__}"
        )

    if not isinstance(items, list):
        raise LangfuseResponseError(
            f"Expected a JSON list under 'data' for the {label} list"
        )

    cursor = _optional_str(meta.get("cursor")) or None
    return tuple(factory(item) for item in items), cursor, meta


@dataclass(frozen=True)
class EvaluatorPage:
    """One page of evaluators plus the cursor for the next page."""

    data: tuple[Evaluator, ...] = ()
    cursor: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def has_more(self) -> bool:
        return bool(self.cursor)

    @classmethod
    def from_api(cls, payload: Any) -> EvaluatorPage:
        items, cursor, meta = _page_from_api(payload, "evaluator", Evaluator.from_api)
        return cls(data=items, cursor=cursor, meta=meta)


@dataclass(frozen=True)
class EvaluatorVersionPage:
    """One page of an evaluator's version history."""

    data: tuple[EvaluatorVersion, ...] = ()
    cursor: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def has_more(self) -> bool:
        return bool(self.cursor)

    @classmethod
    def from_api(cls, payload: Any, evaluator_id: str = "") -> EvaluatorVersionPage:
        items, cursor, meta = _page_from_api(
            payload,
            "evaluator version",
            lambda item: EvaluatorVersion.from_api(item, evaluator_id),
        )
        return cls(data=items, cursor=cursor, meta=meta)
