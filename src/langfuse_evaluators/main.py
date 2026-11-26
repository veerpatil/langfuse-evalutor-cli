"""CLI entry point for managing Langfuse evaluators via the v2 API."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

from .client import (
    API_PATH,
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
from .errors import LangfuseAPIError, LangfuseError
from .evaluators import ALL_EVALUATORS, CODE_EVALUATORS, LLM_AS_JUDGE_EVALUATORS
from .models import Evaluator, EvaluatorPage, EvaluatorVersion, EvaluatorVersionPage


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
        "delete", help="Permanently delete an evaluator by its evaluator id"
    )
    delete_parser.add_argument("evaluator_id")
    delete_parser.add_argument(
        "--yes",
        action="store_true",
        help="Delete without prompting; deletion is permanent",
    )
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


def _format_evaluator(evaluator: Evaluator) -> str:
    version = evaluator.version if evaluator.version is not None else "?"
    return f"{evaluator.evaluator_id}  {evaluator.name}  v{version}"


def _format_version(version: EvaluatorVersion) -> str:
    timestamp = version.created_at or "unknown"
    return f"v{version.version}  {timestamp}"


def _render_listing(
    *,
    fetch_all: bool,
    fetch_page: Callable[[], EvaluatorPage | EvaluatorVersionPage],
    iter_items: Callable[[], Iterator[Evaluator | EvaluatorVersion]],
    formatter: Callable[[Evaluator | EvaluatorVersion], str],
    empty_message: str,
    json_output: bool,
    cursor: str | None = None,
    empty_message_for_cursor: str = "",
    progress_message: str = "",
) -> int:
    """Render one page or every page of a cursor-paginated resource.

    ``fetch_page`` fetches a single page and ``iter_items`` yields every
    item across pages. Both CLI listing commands share this scaffolding;
    only the fetch calls, formatter, and empty-state messages differ.

    ``iter_items`` may issue many sequential requests, so a progress line
    goes to stderr first to keep an interactive run from looking hung,
    and an empty result under ``--cursor`` is reported as the end of the
    pagination rather than an empty account.
    """
    if fetch_all:
        if progress_message:
            print(progress_message, file=sys.stderr)
        items = list(iter_items())
        page_meta = None
        next_cursor = None
    else:
        page = fetch_page()
        items = list(page.data)
        page_meta = dict(page.meta)
        next_cursor = page.cursor

    if json_output:
        payload = {"data": [item.to_dict() for item in items]}
        if page_meta is not None:
            payload["meta"] = page_meta
            payload["cursor"] = next_cursor
        print(json.dumps(payload, indent=2))
        return 0

    if not items:
        print(empty_message_for_cursor if cursor else empty_message)
        return 0

    for item in items:
        print(formatter(item))
    if next_cursor:
        print(
            f"\nNext cursor: {next_cursor} "
            f"(pass --cursor {next_cursor} to see more results)"
        )
    return 0


def _list(args: argparse.Namespace) -> int:
    config = get_config()
    return _render_listing(
        fetch_all=args.fetch_all,
        fetch_page=lambda: list_evaluators(
            config, limit=args.limit, cursor=args.cursor
        ),
        iter_items=lambda: iter_evaluators(
            config, limit=args.limit, cursor=args.cursor
        ),
        formatter=_format_evaluator,
        empty_message="No evaluators found.",
        json_output=args.json,
        cursor=args.cursor,
        empty_message_for_cursor="No further evaluators for this cursor.",
        progress_message="Fetching all evaluators...",
    )


def _get(args: argparse.Namespace) -> int:
    config = get_config()
    evaluator = get_evaluator(args.evaluator_id, config)
    if args.json:
        print(json.dumps(evaluator.to_dict(), indent=2))
    else:
        print(_format_evaluator(evaluator))
    return 0


def _load_update_payload(path: Path) -> dict:
    try:
        text = path.read_text()
    except OSError as exc:
        raise OSError(f"Could not read update payload {path}: {exc}") from exc
    try:
        changes = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Update payload in {path} is not valid JSON "
            f"({exc.msg} at line {exc.lineno} column {exc.colno})"
        ) from exc
    if not isinstance(changes, dict):
        # Keep payload-shape errors on the ValueError idiom used by
        # models.validate_evaluator_payload for non-mapping payloads.
        raise ValueError(  # noqa: TRY004
            f"Update payload in {path} must be a JSON object"
        )
    return changes


def _update(args: argparse.Namespace) -> int:
    changes = _load_update_payload(args.file)
    config = get_config()
    evaluator = update_evaluator(args.evaluator_id, changes, config)
    if args.json:
        print(json.dumps(evaluator.to_dict(), indent=2))
    else:
        print(f"Updated {_format_evaluator(evaluator)}")
    return 0


def _confirm_delete(evaluator_id: str, assume_yes: bool) -> bool | None:
    """Return whether a permanent delete should proceed.

    Deletion has no undo path, so non-interactive runs must opt in with
    ``--yes`` and interactive runs must confirm the evaluator id.
    ``None`` means the request was refused because it could not be
    confirmed, which is an error; ``False`` is a deliberate decline.
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(
            f"Refusing to delete {evaluator_id} without confirmation; "
            "pass --yes to delete it permanently.",
            file=sys.stderr,
        )
        return None
    try:
        answer = input(f"Permanently delete evaluator {evaluator_id}? [y/N] ")
    except EOFError:
        # End-of-input (Ctrl-D) is not an answer; treat it as a decline
        # instead of letting a traceback escape the CLI.
        print()
        return False
    return answer.strip().lower() in {"y", "yes"}


def _delete(args: argparse.Namespace) -> int:
    confirmation = _confirm_delete(args.evaluator_id, args.yes)
    if confirmation is None:
        return 1
    if not confirmation:
        print("Deletion cancelled.")
        return 0
    config = get_config()
    delete_evaluator(args.evaluator_id, config)
    if args.json:
        print(json.dumps({"deleted": args.evaluator_id}, indent=2))
    else:
        print(f"Deleted evaluator {args.evaluator_id}")
    return 0


def _versions(args: argparse.Namespace) -> int:
    config = get_config()
    return _render_listing(
        fetch_all=args.fetch_all,
        fetch_page=lambda: list_evaluator_versions(
            args.evaluator_id, config, limit=args.limit, cursor=args.cursor
        ),
        iter_items=lambda: iter_evaluator_versions(
            args.evaluator_id, config, limit=args.limit, cursor=args.cursor
        ),
        formatter=_format_version,
        empty_message=f"No versions found for {args.evaluator_id}.",
        json_output=args.json,
        cursor=args.cursor,
        empty_message_for_cursor="No further versions for this cursor.",
        progress_message=f"Fetching all versions for {args.evaluator_id}...",
    )


COMMANDS = {
    "create": _create,
    "list": _list,
    "get": _get,
    "update": _update,
    "delete": _delete,
    "versions": _versions,
}


_ERROR_HINTS = {
    "authentication_error": (
        "Check LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY (or your .env file)."
    ),
    "permission_error": (
        "Check that the API keys have permission to manage evaluators."
    ),
    "not_found": "Verify the evaluator id with `create-evaluators list`.",
    "rate_limit_error": "Wait a moment and retry the request.",
    "conflict": (
        "An evaluator with that name already exists; check it with "
        "`create-evaluators list` and change it with `create-evaluators update`."
    ),
    "validation_error": "Check the request payload and try again.",
}


def _error_hint(exc: BaseException) -> str | None:
    """Return a next-step hint for the common error kinds.

    ``LangfuseTransportError`` is not mapped here because its message
    already tells the user to check ``LANGFUSE_HOST`` and the network, so
    a hint would repeat the same wording on the next line.
    """
    if isinstance(exc, LangfuseAPIError):
        if exc.status_code == 404 and exc.path == API_PATH:
            return (
                "This server may not expose the v2 evaluators endpoint; "
                "pin langfuse-evaluators 0.1.0 for older self-hosted servers."
            )
        return _ERROR_HINTS.get(exc.error_kind)
    return None


def main():
    parser = _build_parser()
    args = parser.parse_args()

    try:
        exit_code = COMMANDS[args.command](args)
    except (LangfuseError, RuntimeError, TypeError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        hint = _error_hint(exc)
        if hint:
            print(f"Hint: {hint}", file=sys.stderr)
        sys.exit(1)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
