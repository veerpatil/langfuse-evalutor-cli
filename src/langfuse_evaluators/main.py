"""CLI entry point for creating Langfuse evaluators."""

import argparse
import json
import sys

from .client import create_evaluators
from .evaluators import ALL_EVALUATORS, CODE_EVALUATORS, LLM_AS_JUDGE_EVALUATORS


def main():
    parser = argparse.ArgumentParser(
        description="Create Langfuse evaluators via the unstable API"
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
    args = parser.parse_args()

    if args.type == "llm":
        evaluators = LLM_AS_JUDGE_EVALUATORS
    elif args.type == "code":
        evaluators = CODE_EVALUATORS
    else:
        evaluators = ALL_EVALUATORS

    print(f"Creating {len(evaluators)} evaluator(s)...\n", flush=True)

    try:
        results = create_evaluators(evaluators)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

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
            if status != 200:
                msg = result["body"].get("message", "Unknown error")
                print(f"    └─ {msg}")

    print(f"\nDone: {success} succeeded, {failed} failed")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
