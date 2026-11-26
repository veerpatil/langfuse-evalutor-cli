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

`LANGFUSE_HOST` defaults to `http://localhost:3000` if it is not set. A base
URL with an `http://` or `https://` scheme, a plain `host[:port]`, and an
optional path prefix work, so self-hosted instances and path-mounted
deployments are supported and `https://example.com/langfuse` targets
`https://example.com/langfuse/api/public/v2/evaluators`. Query strings,
fragments, embedded userinfo, and non-numeric ports are not supported, and a
host without an `http://` or `https://` scheme is rejected before any request
is sent. Use `http://` only for a loopback host or a TLS-terminating local
proxy: the API keys are sent as Basic auth on every request, so a remote
plaintext host exposes them, and the CLI warns when it sees one.

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
uv run create-evaluators list --all --cursor <cursor>  # resume, then follow
uv run create-evaluators list --all --json   # machine-readable output
```

### Retrieve, update, and delete an evaluator

```bash
uv run create-evaluators get <evaluator-id>
uv run create-evaluators update <evaluator-id> --file update.json
uv run create-evaluators delete <evaluator-id>           # prompts to confirm
uv run create-evaluators delete <evaluator-id> --yes     # non-interactive
```

Deleting an evaluator is permanent and has no undo path, so `delete` prompts
for confirmation and requires `--yes` when standard input is not a terminal.

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
- `list --all` and `versions --all` start from `--cursor` when it is supplied,
  then follow the cursors the API returns.
- Errors keep the structured Langfuse error body and are mapped to stable kinds:
  `validation_error` (400/422), `authentication_error` (401),
  `permission_error` (403), `not_found` (404), `conflict` (409),
  `rate_limit_error` (429), `server_error` (5xx), and `api_error` for any other
  status.

## Migrating from the unstable API

This is a `0.2.0` release; the `0.1.0` release still targets the unstable
endpoint. See the release notes below for what changed.

- The endpoint moved from `/api/public/unstable/evaluators` to
  `/api/public/v2/evaluators`. `0.2.0` requires a Langfuse server that exposes
  the v2 evaluators endpoint; a self-hosted deployment that only serves the
  unstable endpoint will start returning `not_found`. Pin
  `langfuse-evaluators==0.1.0` for those installations until the server is
  upgraded. The exact minimum self-hosted Langfuse version that ships this
  endpoint could not be confirmed while this release was written, so check
  your server's API reference before upgrading.
- **Python API break:** `create_evaluator()` now returns an `Evaluator` and
  raises `LangfuseAPIError` / `LangfuseTransportError` / `ValueError` instead
  of returning a `{status, reason, body}` dict. Callers that read
  `result["status"]` must switch to the returned object and to exceptions.
  The batch helper `create_evaluators()` keeps the legacy per-item dict shape
  (`status`, `reason`, `body`, `name`) and adds `evaluatorId` and `version`.
  Callers that cannot migrate yet can use `create_evaluator_result()`, a
  compatibility shim that still returns the `0.1.0` `{status, reason, body}`
  dict and reports failures in that dict instead of raising.
- Evaluators are identified by `evaluatorId` instead of by name. The
  `create-evaluators` CLI still reports `name` for readability but also reports
  `evaluatorId`; downstream automation should key on `evaluatorId`.
- The client no longer performs name-based lookups.
- v2 responses include `version`, `createdAt`, and `updatedAt`. Update calls
  create a new version, retrievable through the `versions` command.
- Errors now expose a structured `body` plus a stable `error_kind`. Code that
  matched on message strings should switch to `error_kind` or
  `LangfuseAPIError.status_code`.
- `LANGFUSE_HOST` now requires an explicit `http://` or `https://` scheme.
  `0.1.0` accepted a schemeless value such as `localhost:3000`; the client now
  rejects it before sending a request, because a schemeless value produces a
  malformed request line. Prefix the value with the scheme you mean.
- The `create-evaluators` entry point keeps its historical name for backward
  compatibility even though it now also manages evaluators through the `list`,
  `get`, `update`, `delete`, and `versions` subcommands. A neutral alias is
  not added in this release.
- While the v2 API reference was unreachable, the client tolerates both a bare
  object/list and a `data`-enveloped response, and reads either `id` or
  `evaluatorId`. That leniency is temporary; pin it to the documented shape
  and remove the fallbacks once the contract is confirmed against a live v2
  instance.

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

The suite has a unit layer that replaces `http.client` with a fake, plus a
small integration layer in `tests/test_integration.py` that runs the client
against a real local HTTP server.

## Notes

- The API path used by this project is `/api/public/v2/evaluators`.
- `LANGFUSE_HOST` may include a path prefix, which is preserved on every
  request.
- Credentials are validated before the request is sent; values containing
  control characters or non-ASCII characters are rejected without echoing the
  value.
- Code evaluators use TypeScript source code and set `sourceCodeLanguage` to `TYPESCRIPT`.
- The CLI exits with status code `1` if any evaluator creation request fails or if a
  management command fails.
