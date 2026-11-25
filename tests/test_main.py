"""CLI tests for the langfuse_evaluators entry point."""

from __future__ import annotations

import contextlib
import io
import json
import sys

from langfuse_evaluators import main as main_module
from langfuse_evaluators.errors import LangfuseAPIError
from langfuse_evaluators.models import (
    Evaluator,
    EvaluatorPage,
    EvaluatorVersion,
    EvaluatorVersionPage,
)

CONFIG = {"host": "http://localhost:3000", "credentials": "encoded"}
EVALUATOR = Evaluator(
    evaluator_id="eval-1",
    name="JSON Parseable Output",
    type="code",
    version=3,
    raw={"id": "eval-1", "name": "JSON Parseable Output", "version": 3},
)
CREATED_RESULT = {
    "status": 201,
    "reason": "Created",
    "body": {"id": "eval-1", "name": "JSON Parseable Output", "version": 1},
    "name": "JSON Parseable Output",
    "evaluatorId": "eval-1",
    "version": 1,
}


def run_cli(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["create-evaluators", *argv])
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            main_module.main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 0
    return code, out.getvalue(), err.getvalue()


def stub_config(monkeypatch):
    monkeypatch.setattr(main_module, "get_config", lambda: CONFIG)


def test_default_invocation_creates_evaluators(monkeypatch):
    monkeypatch.setattr(
        main_module, "create_evaluators", lambda evaluators: [CREATED_RESULT]
    )

    code, out, _ = run_cli(monkeypatch, [])

    assert code == 0
    assert "Creating 10 evaluator(s)" in out
    assert "✓ [201] JSON Parseable Output" in out
    assert "id: eval-1 version: 1" in out
    assert "Done: 1 succeeded, 0 failed" in out


def test_create_only_code_evaluators(monkeypatch):
    captured = {}

    def fake_create(evaluators):
        captured["count"] = len(evaluators)
        return []

    monkeypatch.setattr(main_module, "create_evaluators", fake_create)

    code, out, _ = run_cli(monkeypatch, ["--type", "code"])

    assert code == 0
    assert captured["count"] == 6
    assert "Creating 6 evaluator(s)" in out


def test_create_reports_failures_and_exits_non_zero(monkeypatch):
    failed = dict(
        CREATED_RESULT,
        status=422,
        reason="Unprocessable Entity",
        body={"message": "name is required"},
        evaluatorId=None,
        version=None,
    )
    monkeypatch.setattr(main_module, "create_evaluators", lambda evaluators: [failed])

    code, out, _ = run_cli(monkeypatch, [])

    assert code == 1
    assert "✗ [422]" in out
    assert "name is required" in out
    assert "Done: 0 succeeded, 1 failed" in out


def test_create_json_output_keeps_evaluator_id(monkeypatch):
    monkeypatch.setattr(
        main_module, "create_evaluators", lambda evaluators: [CREATED_RESULT]
    )

    code, out, _ = run_cli(monkeypatch, ["--json"])

    assert code == 0
    assert '"evaluatorId": "eval-1"' in out


def test_list_json_output(monkeypatch):
    stub_config(monkeypatch)
    page = EvaluatorPage(
        data=(EVALUATOR,), cursor="next-cursor", meta={"cursor": "next-cursor"}
    )
    monkeypatch.setattr(main_module, "list_evaluators", lambda *a, **kw: page)

    code, out, _ = run_cli(monkeypatch, ["list", "--json"])

    assert code == 0
    payload = json.loads(out)
    assert payload["data"][0]["id"] == "eval-1"
    assert payload["cursor"] == "next-cursor"


def test_list_text_output_prints_next_cursor(monkeypatch):
    stub_config(monkeypatch)
    page = EvaluatorPage(data=(EVALUATOR,), cursor="next-cursor")
    monkeypatch.setattr(main_module, "list_evaluators", lambda *a, **kw: page)

    code, out, _ = run_cli(monkeypatch, ["list"])

    assert code == 0
    assert "eval-1  JSON Parseable Output  v3" in out
    assert "Next cursor: next-cursor" in out


def test_list_all_follows_every_page(monkeypatch):
    stub_config(monkeypatch)
    monkeypatch.setattr(
        main_module,
        "iter_evaluators",
        lambda config, limit: iter([EVALUATOR]),
    )

    code, out, _ = run_cli(monkeypatch, ["list", "--all", "--json"])

    assert code == 0
    payload = json.loads(out)
    assert [item["id"] for item in payload["data"]] == ["eval-1"]


def test_get_evaluator_by_id(monkeypatch):
    stub_config(monkeypatch)
    monkeypatch.setattr(
        main_module, "get_evaluator", lambda evaluator_id, config: EVALUATOR
    )

    code, out, _ = run_cli(monkeypatch, ["get", "eval-1"])

    assert code == 0
    assert "eval-1  JSON Parseable Output  v3" in out


def test_missing_evaluator_exits_with_error(monkeypatch):
    stub_config(monkeypatch)

    def raise_not_found(evaluator_id, config):
        raise LangfuseAPIError(
            404,
            "Not Found",
            {"message": "Evaluator not found"},
            "GET",
            "/api/public/v2/evaluators/eval-1",
        )

    monkeypatch.setattr(main_module, "get_evaluator", raise_not_found)

    code, _, err = run_cli(monkeypatch, ["get", "eval-1"])

    assert code == 1
    assert "not_found" in err
    assert "Evaluator not found" in err


def test_update_reads_payload_file(monkeypatch, tmp_path):
    stub_config(monkeypatch)
    captured = {}

    def fake_update(evaluator_id, changes, config):
        captured.update(evaluator_id=evaluator_id, changes=changes)
        return EVALUATOR

    monkeypatch.setattr(main_module, "update_evaluator", fake_update)
    payload_file = tmp_path / "update.json"
    payload_file.write_text(json.dumps({"description": "updated"}))

    code, out, _ = run_cli(
        monkeypatch, ["update", "eval-1", "--file", str(payload_file)]
    )

    assert code == 0
    assert captured == {"evaluator_id": "eval-1", "changes": {"description": "updated"}}
    assert "Updated eval-1  JSON Parseable Output  v3" in out


def test_update_rejects_non_object_payload(monkeypatch, tmp_path):
    stub_config(monkeypatch)
    payload_file = tmp_path / "update.json"
    payload_file.write_text(json.dumps(["not", "an", "object"]))

    code, _, err = run_cli(
        monkeypatch, ["update", "eval-1", "--file", str(payload_file)]
    )

    assert code == 1
    assert "must be a JSON object" in err


def test_delete_evaluator(monkeypatch):
    stub_config(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        main_module,
        "delete_evaluator",
        lambda evaluator_id, config: captured.update(evaluator_id=evaluator_id),
    )

    code, out, _ = run_cli(monkeypatch, ["delete", "eval-1"])

    assert code == 0
    assert captured == {"evaluator_id": "eval-1"}
    assert "Deleted evaluator eval-1" in out


def test_versions_all_json_output(monkeypatch):
    stub_config(monkeypatch)
    version = EvaluatorVersion(
        evaluator_id="eval-1",
        version=2,
        created_at="2026-02-01T00:00:00Z",
        raw={"version": 2, "createdAt": "2026-02-01T00:00:00Z"},
    )
    monkeypatch.setattr(
        main_module,
        "iter_evaluator_versions",
        lambda evaluator_id, config, limit: iter([version]),
    )

    code, out, _ = run_cli(monkeypatch, ["versions", "eval-1", "--all", "--json"])

    assert code == 0
    payload = json.loads(out)
    assert payload["data"][0]["version"] == 2


def test_versions_page_output(monkeypatch):
    stub_config(monkeypatch)
    version = EvaluatorVersion(evaluator_id="eval-1", version=1, raw={"version": 1})
    page = EvaluatorVersionPage(data=(version,), cursor="curve")
    monkeypatch.setattr(
        main_module,
        "list_evaluator_versions",
        lambda *a, **kw: page,
    )

    code, out, _ = run_cli(monkeypatch, ["versions", "eval-1"])

    assert code == 0
    assert "v1  unknown" in out
    assert "Next cursor: curve" in out


def test_configuration_errors_exit_non_zero(monkeypatch):
    def raise_config_error():
        raise RuntimeError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set")

    monkeypatch.setattr(main_module, "get_config", raise_config_error)

    code, _, err = run_cli(monkeypatch, ["list"])

    assert code == 1
    assert "LANGFUSE_PUBLIC_KEY" in err


def test_json_flag_before_subcommand_is_preserved(monkeypatch):
    stub_config(monkeypatch)
    page = EvaluatorPage(data=(EVALUATOR,), cursor=None)
    monkeypatch.setattr(main_module, "list_evaluators", lambda *a, **kw: page)

    code, out, _ = run_cli(monkeypatch, ["--json", "list"])

    assert code == 0
    assert json.loads(out)["data"][0]["id"] == "eval-1"
