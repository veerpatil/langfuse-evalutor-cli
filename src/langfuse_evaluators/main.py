"""CLI entry point for managing Langfuse evaluators via the v2 API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .client import (
    DEFAULT_PAGE_SIZE,
    create_evaluators,
    delete_evaluator,
    get_evaluator,
    iter_evaluator_versions,
    iter_evaluators,
    list_evaluator_versions,
    list_evaluators,
    update_evaluator,
)
from .config import get_config
from .errors import LangfuseError
from .evaluators import ALL_EVALUATORS, CODE_EVALUATORS, LLM_AS_JUDGE_EVALUATORS


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage Langfuse evaluators via the v2 API"
    )
    parser.add_argument(
        "--type",
        choices=["all", "llm", "code"],
        default="all",
        help="Which evaluator type to create (default: all)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    # Running `create-evaluators` without a subcommand keeps the historical
    # behaviour of creating every predefined evaluator.
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser(
        "list", help="List evaluators using cursor pagination"
    )
    _add_pagination_arguments(list_parser)

    get_parser = subparsers.add_parser(
        "get", help="Retrieve an evaluator by its evaluator id"
    )
    get_parser.add_argument("evaluator_id")
    _add_json_argument(get_parser)

    update_parser = subparsers.add_parser(
        "update", help="Update an evaluator by its evaluator id"
    )
    update_parser.add_argument("evaluator_id")
    update_parser.add_argument(
        "--file",
        required=True,
        type=Path,
        help="Path to a JSON file with the fields to update",
    )
    _add_json_argument(update_parser)

    delete_parser = subparsers.add_parser(
        "delete", help="Delete an evaluator by its evaluator id"
    )
    delete_parser.add_argument("evaluator_id")
    _add_json_argument(delete_parser)

    versions_parser = subparsers.add_parser(
        "versions", help="List an evaluator's version history"
    )
    versions_parser.add_argument("evaluator_id")
    _add_pagination_arguments(versions_parser)

    # `set_defaults` must run after `add_subparsers`, whose action installs its
    # own `None` default for `command`.
    parser.set_defaults(command="create")

    return parser


def _add_json_argument(parser: argparse.ArgumentParser) -> None:
    # SUPPRESS keeps a subcommand from overwriting `--json` that was
    # already supplied before the subcommand.
    parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Output results as JSON",
    )


def _add_pagination_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"Page size, 1-100 (default: {DEFAULT_PAGE_SIZE})",
    )
    parser.add_argument(
        "--cursor",
        default=None,
        help="Cursor returned by a previous listing",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="fetch_all",
        help="Follow cursors and print every result",
    )
    _add_json_argument(parser)


def _create(args: argparse.Namespace) -> int:
    if args.type == "llm":
        evaluators = LLM_AS_JUDGE_EVALUATORS
    elif args.type == "code":
        evaluators = CODE_EVALUATORS
    else:
        evaluators = ALL_EVALUATORS

    print(f"Creating {len(evaluators)} evaluator(s)...\n", flush=True)

    results = create_evaluators(evaluators)

    success = 0
    failed = 0

    for result in results:
        status = result["status"]
        name = result["name"]

        if 200 <= status < 300:
            success += 1
            marker = "✓"
        else:
            failed += 1
            marker = "✗"

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"  {marker} [{status}] {name}")
            if 200 <= status < 300:
                print(
                    f"    └─ id: {result['evaluatorId']} version: {result['version']}"
                )
            else:
                msg = result["body"].get("message", "Unknown error")
                print(f"    └─ {msg}")

    print(f"\nDone: {success} succeeded, {failed} failed")
    return 1 if failed > 0 else 0


def _format_evaluator(evaluator) -> str:
    version = evaluator.version if evaluator.version is not None else "?"
    return f"{evaluator.evaluator_id}  {evaluator.name}  v{version}"


def _format_version(version) -> str:
    timestamp = version.created_at or "unknown"
    return f"v{version.version}  {timestamp}"


def _list(args: argparse.Namespace) -> int:
    config = get_config()
    if args.fetch_all:
        evaluators = list(iter_evaluators(config, limit=args.limit))
        page_meta = None
        cursor = None
    else:
        page = list_evaluators(config, limit=args.limit, cursor=args.cursor)
        evaluators = list(page.data)
        page_meta = dict(page.meta)
        cursor = page.cursor

    if args.json:
        payload = {"data": [item.to_dict() for item in evaluators]}
        if page_meta is not None:
            payload["meta"] = page_meta
            payload["cursor"] = cursor
        print(json.dumps(payload, indent=2))
        return 0

    for evaluator in evaluators:
        print(_format_evaluator(evaluator))
    if cursor:
        print(f"\nNext cursor: {cursor}")
    return 0


def _get(args: argparse.Namespace) -> int:
    evaluator = get_evaluator(args.evaluator_id, get_config())
    if args.json:
        print(json.dumps(evaluator.to_dict(), indent=2))
    else:
        print(_format_evaluator(evaluator))
    return 0


def _load_update_payload(path: Path) -> dict:
    changes = json.loads(path.read_text())
    if not isinstance(changes, dict):
        raise TypeError(f"Update payload in {path} must be a JSON object")
    return changes


def _update(args: argparse.Namespace) -> int:
    changes = _load_update_payload(args.file)
    evaluator = update_evaluator(args.evaluator_id, changes, get_config())
    if args.json:
        print(json.dumps(evaluator.to_dict(), indent=2))
    else:
        print(f"Updated {_format_evaluator(evaluator)}")
    return 0


def _delete(args: argparse.Namespace) -> int:
    delete_evaluator(args.evaluator_id, get_config())
    if args.json:
        print(json.dumps({"deleted": args.evaluator_id}, indent=2))
    else:
        print(f"Deleted evaluator {args.evaluator_id}")
    return 0


def _versions(args: argparse.Namespace) -> int:
    config = get_config()
    if args.fetch_all:
        versions = list(
            iter_evaluator_versions(args.evaluator_id, config, limit=args.limit)
        )
        page_meta = None
        cursor = None
    else:
        page = list_evaluator_versions(
            args.evaluator_id, config, limit=args.limit, cursor=args.cursor
        )
        versions = list(page.data)
        page_meta = dict(page.meta)
        cursor = page.cursor

    if args.json:
        payload = {"data": [item.to_dict() for item in versions]}
        if page_meta is not None:
            payload["meta"] = page_meta
            payload["cursor"] = cursor
        print(json.dumps(payload, indent=2))
        return 0

    for version in versions:
        print(_format_version(version))
    if cursor:
        print(f"\nNext cursor: {cursor}")
    return 0


COMMANDS = {
    "create": _create,
    "list": _list,
    "get": _get,
    "update": _update,
    "delete": _delete,
    "versions": _versions,
}


def main():
    parser = _build_parser()
    args = parser.parse_args()

    try:
        exit_code = COMMANDS[args.command](args)
    except (LangfuseError, RuntimeError, TypeError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
