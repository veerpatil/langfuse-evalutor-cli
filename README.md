# Langfuse Evaluators

Create and manage predefined Langfuse evaluators through the Langfuse unstable public API.

This project provides a small Python CLI that creates two kinds of evaluators:

- LLM-as-Judge evaluators for judging assistant responses with model-based prompts.
- Code evaluators written in TypeScript for deterministic checks such as JSON validity, exact match, output length, and tool-call validation.

## Project Structure

```text
.
├── pyproject.toml
├── uv.lock
├── src/
│   └── langfuse_evaluators/
│       ├── main.py
│       ├── client.py
│       ├── config.py
│       └── evaluators/
│           ├── llm_as_judge.py
│           └── code_evaluators.py
└── README.md
```

Key files:

- `src/langfuse_evaluators/main.py`: CLI entry point.
- `src/langfuse_evaluators/client.py`: sends evaluator creation requests to Langfuse.
- `src/langfuse_evaluators/config.py`: loads Langfuse credentials and host configuration.
- `src/langfuse_evaluators/evaluators/llm_as_judge.py`: predefined LLM-as-Judge evaluators.
- `src/langfuse_evaluators/evaluators/code_evaluators.py`: predefined TypeScript code evaluators.

## Requirements

- Python 3.10 or newer
- `uv`
- A running Langfuse instance
- Langfuse public and secret API keys

## Setup

Install or sync the project environment:

```bash
uv sync
```

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Then update the values:

```bash
LANGFUSE_PUBLIC_KEY=your_public_key
LANGFUSE_SECRET_KEY=your_secret_key
LANGFUSE_HOST=http://localhost:3000
```

`LANGFUSE_HOST` defaults to `http://localhost:3000` if it is not set.

## Usage

Create all evaluators:

```bash
uv run create-evaluators
```

Create only LLM-as-Judge evaluators:

```bash
uv run create-evaluators --type llm
```

Create only code evaluators:

```bash
uv run create-evaluators --type code
```

Print API results as JSON:

```bash
uv run create-evaluators --json
```

You can also combine options:

```bash
uv run create-evaluators --type code --json
```

## Available Evaluators

### LLM-as-Judge

- `Product Version Accuracy`: checks whether the response references the correct product version.
- `Response Relevance`: checks whether the response directly answers the user's question.
- `Factual Correctness`: checks whether the response is consistent with ground truth.
- `Response Completeness`: checks whether the response addresses all required parts of the question.

### Code Evaluators

- `JSON Parseable Output`: checks whether the observation output is valid JSON.
- `Output Not Empty`: checks whether the output is present and non-empty.
- `Exact Match`: checks whether output exactly matches expected experiment output.
- `Contains Required Keywords`: checks whether output includes required keywords from experiment metadata.
- `Output Length Check`: checks whether output stays within a fixed length limit.
- `Tool Call Validator`: checks whether tool calls include required names and arguments.

## Configuration

The CLI reads configuration from environment variables or from a root-level `.env` file.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `LANGFUSE_PUBLIC_KEY` | Yes | None | Langfuse public API key |
| `LANGFUSE_SECRET_KEY` | Yes | None | Langfuse secret API key |
| `LANGFUSE_HOST` | No | `http://localhost:3000` | Langfuse host URL |

If `LANGFUSE_PUBLIC_KEY` or `LANGFUSE_SECRET_KEY` is missing, the CLI exits with an error.

## Notes

- The API path used by this project is `/api/public/unstable/evaluators`.
- Code evaluators use TypeScript source code and set `sourceCodeLanguage` to `TYPESCRIPT`.
- The CLI exits with status code `1` if any evaluator creation request fails.
