# Langfuse Evaluators

Create and manage predefined Langfuse evaluators through the stable Langfuse
v2 evaluators API.

This project provides a small Python CLI that manages two kinds of evaluators:

- LLM-as-Judge evaluators for judging assistant responses with model-based prompts.
- Code evaluators written in TypeScript for deterministic checks such as JSON validity, exact match, output length, and tool-call validation.

Evaluators are addressed by their stable evaluator id (`evaluatorId`), listing
uses cursor pagination, and Langfuse errors are mapped to stable error kinds so
callers never have to parse error message strings.

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
│       ├── errors.py
│       ├── models.py
│       └── evaluators/
│           ├── llm_as_judge.py
│           └── code_evaluators.py
├── tests/
└── README.md
```

Key files:

- `src/langfuse_evaluators/main.py`: CLI entry point.
- `src/langfuse_evaluators/client.py`: sends requests to the Langfuse v2 evaluators API.
- `src/langfuse_evaluators/models.py`: request validation and v2 evaluator/version response models.
- `src/langfuse_evaluators/errors.py`: structured Langfuse API errors and status-to-kind mapping.
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

`LANGFUSE_HOST` defaults to `http://localhost:3000` if it is not set. Any base
URL works, including self-hosted instances and paths; requests always target
`<host>/api/public/v2/evaluators`.

## Usage

### Create evaluators

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

Each create result includes the historical `status`, `reason`, `body`, and
`name` keys plus the stable `evaluatorId` and `version` returned by the v2 API.

### List evaluators

```bash
uv run create-evaluators list
uv run create-evaluators list --limit 25 --cursor <cursor>
uv run create-evaluators list --all          # follow every cursor
uv run create-evaluators list --all --json   # machine-readable output
```

### Retrieve, update, and delete an evaluator

```bash
uv run create-evaluators get <evaluator-id>
uv run create-evaluators update <evaluator-id> --file update.json
uv run create-evaluators delete <evaluator-id>
```

`update.json` is a JSON object containing only the fields to change, for
example:

```json
{"description": "Updated description"}
```

### Version history

```bash
uv run create-evaluators versions <evaluator-id>
uv run create-evaluators versions <evaluator-id> --all --json
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
Requests use HTTP Basic authentication built from those two keys. Credentials
and evaluator payloads are never included in error messages or log output.

## API behavior

- Base endpoint: `/api/public/v2/evaluators`.
- Create: `POST /api/public/v2/evaluators`.
- List: `GET /api/public/v2/evaluators?limit=<1-100>&cursor=<cursor>`. Responses
  return `data` plus `meta.cursor`; the next page is requested with that cursor.
  `list --all` follows cursors, de-duplicates by evaluator id, and stops if the
  API repeats a cursor.
- Retrieve: `GET /api/public/v2/evaluators/<evaluatorId>`.
- Update: `PUT /api/public/v2/evaluators/<evaluatorId>`.
- Delete: `DELETE /api/public/v2/evaluators/<evaluatorId>`.
- Versions: `GET /api/public/v2/evaluators/<evaluatorId>/versions`.
- Errors keep the structured Langfuse error body and are mapped to stable kinds:
  `validation_error` (400/422), `authentication_error` (401),
  `permission_error` (403), `not_found` (404), `conflict` (409),
  `rate_limit_error` (429), `server_error` (5xx), and `api_error` for any other
  status.

## Migrating from the unstable API

- The endpoint moved from `/api/public/unstable/evaluators` to
  `/api/public/v2/evaluators`.
- Evaluators are identified by `evaluatorId` instead of by name. The
  `create-evaluators` CLI still reports `name` for readability but also reports
  `evaluatorId`; downstream automation should key on `evaluatorId`.
- The client no longer performs name-based lookups.
- v2 responses include `version`, `createdAt`, and `updatedAt`. Update calls
  create a new version, retrievable through the `versions` command.
- Errors now expose a structured `body` plus a stable `error_kind`. Code that
  matched on message strings should switch to `error_kind` or
  `LangfuseAPIError.status_code`.

## Development

Run the test suite (pytest is provided by the `dev` dependency group):

```bash
uv sync
uv run pytest
```

Without `uv`, the tests also run from a checkout:

```bash
python -m pytest
```

## Notes

- The API path used by this project is `/api/public/v2/evaluators`.
- Code evaluators use TypeScript source code and set `sourceCodeLanguage` to `TYPESCRIPT`.
- The CLI exits with status code `1` if any evaluator creation request fails or if a
  management command fails.
