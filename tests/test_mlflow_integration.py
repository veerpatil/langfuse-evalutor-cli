"""Integration tests for the MLflow scorer client against a local server.

The unit layer replaces ``http.client`` with a fake, so these tests cover
what a fake cannot: that the client speaks HTTP to a real server, sends
the request shapes the MLflow routes expect, and parses real responses.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from langfuse_evaluators.mlflow_scorers import client
from langfuse_evaluators.mlflow_scorers.errors import MLflowAPIError

DEFINITION = '{"name": "Helpfulness", "type": "llm", "prompt": "v1"}'
UPDATED_DEFINITION = '{"name": "Helpfulness", "type": "llm", "prompt": "v2"}'


class ScorerHandler(BaseHTTPRequestHandler):
    """A tiny MLflow scorer stand-in with in-memory state.

    Registering a name always creates a new version, as the MLflow
    tracking store does. A name that collates equal to an existing one
    but is not identical (only case differs here) is reported as
    ``RESOURCE_ALREADY_EXISTS``, mirroring MLflow's database rule.
    """

    server_version = "FakeMLflow/1.0"

    def log_message(self, *args):  # keep pytest output clean
        pass

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def _record(self, body=None) -> None:
        self.server.requests.append(
            {
                "method": self.command,
                "path": urlparse(self.path).path,
                "query": parse_qs(urlparse(self.path).query),
                "content_type": self.headers.get("Content-Type"),
                "body": body,
            }
        )

    def _payload(self, store, version_entry) -> dict:
        return {
            "experiment_id": store["experiment_id"],
            "scorer_name": store["name"],
            "scorer_version": version_entry["version"],
            "serialized_scorer": version_entry["serialized_scorer"],
            "creation_time": version_entry["creation_time"],
            "scorer_id": store["scorer_id"],
        }

    def _latest(self, store):
        return max(store["versions"], key=lambda entry: entry["version"])

    def _find(self, experiment_id, name):
        return self.server.scorers.get((experiment_id, name))

    def _find_or_404(self, experiment_id, name):
        store = self._find(experiment_id, name)
        if store is None:
            self._reply(
                404,
                {
                    "error_code": "RESOURCE_DOES_NOT_EXIST",
                    "message": f"Scorer {name} not found",
                },
            )
        return store

    def do_POST(self) -> None:
        body = self._read_body()
        self._record(body)
        if self.path != f"{client.API_PATH}/register":
            self._reply(
                404, {"error_code": "ENDPOINT_NOT_FOUND", "message": "no route"}
            )
            return

        experiment_id = body["experiment_id"]
        name = body["name"]
        serialized = body["serialized_scorer"]
        colliding = next(
            (
                store
                for (stored_experiment, stored_name), store
                in self.server.scorers.items()
                if stored_experiment == experiment_id
                and stored_name.lower() == name.lower()
                and stored_name != name
            ),
            None,
        )
        if colliding is not None:
            self._reply(
                400,
                {
                    "error_code": "RESOURCE_ALREADY_EXISTS",
                    "message": f"Experiment {experiment_id} already has a scorer "
                    f"whose name collates equal to {name!r}",
                },
            )
            return

        store = self._find(experiment_id, name)
        if store is None:
            store = {
                "experiment_id": experiment_id,
                "name": name,
                "scorer_id": f"scorer-{len(self.server.scorers) + 1}",
                "versions": [],
            }
            self.server.scorers[(experiment_id, name)] = store

        version = len(store["versions"]) + 1
        version_entry = {
            "version": version,
            "serialized_scorer": serialized,
            "creation_time": 1767225600000 + version,
        }
        store["versions"].append(version_entry)
        response = {
            "version": version,
            "scorer_id": store["scorer_id"],
            "experiment_id": experiment_id,
            "name": name,
            "serialized_scorer": serialized,
            "creation_time": version_entry["creation_time"],
        }
        self._reply(201, response)

    def do_GET(self) -> None:
        self._record()
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == f"{client.API_PATH}/list":
            experiment_ids = query.get("experiment_ids")
            if experiment_ids is None:
                experiment_ids = [query["experiment_id"][0]]
            stores = [
                store
                for (experiment_id, _), store in self.server.scorers.items()
                if experiment_id in experiment_ids
            ]
            self._reply(
                200,
                {
                    "scorers": [
                        self._payload(store, self._latest(store))
                        for store in stores
                    ]
                },
            )
            return

        if parsed.path == f"{client.API_PATH}/get":
            store = self._find_or_404(query["experiment_id"][0], query["name"][0])
            if store is None:
                return
            if "version" in query:
                requested = int(query["version"][0])
                entry = next(
                    (
                        candidate
                        for candidate in store["versions"]
                        if candidate["version"] == requested
                    ),
                    None,
                )
                if entry is None:
                    self._reply(
                        404,
                        {
                            "error_code": "RESOURCE_DOES_NOT_EXIST",
                            "message": f"Scorer version {requested} not found",
                        },
                    )
                    return
            else:
                entry = self._latest(store)
            self._reply(200, {"scorer": self._payload(store, entry)})
            return

        if parsed.path == f"{client.API_PATH}/versions":
            store = self._find_or_404(query["experiment_id"][0], query["name"][0])
            if store is None:
                return
            versions = sorted(
                store["versions"], key=lambda entry: entry["version"], reverse=True
            )
            self._reply(
                200,
                {"scorers": [self._payload(store, entry) for entry in versions]},
            )
            return

        self._reply(404, {"error_code": "ENDPOINT_NOT_FOUND", "message": "no route"})

    def do_DELETE(self) -> None:
        body = self._read_body()
        self._record(body)
        if self.path != f"{client.API_PATH}/delete":
            self._reply(
                404, {"error_code": "ENDPOINT_NOT_FOUND", "message": "no route"}
            )
            return

        store = self._find_or_404(body["experiment_id"], body["name"])
        if store is None:
            return

        if "version" in body:
            requested = int(body["version"])
            remaining = [
                entry
                for entry in store["versions"]
                if entry["version"] != requested
            ]
            if len(remaining) == len(store["versions"]):
                self._reply(
                    404,
                    {
                        "error_code": "RESOURCE_DOES_NOT_EXIST",
                        "message": f"Scorer version {requested} not found",
                    },
                )
                return
            store["versions"] = remaining
            if not remaining:
                del self.server.scorers[(store["experiment_id"], store["name"])]
        else:
            del self.server.scorers[(store["experiment_id"], store["name"])]

        self._reply(200, {})


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ScorerHandler)
    httpd.scorers = {}
    httpd.requests = []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture
def live_config(server):
    host, port = server.server_address[:2]
    return {"host": f"http://{host}:{port}", "experiment_id": "exp-1"}


def register(config, experiment_id, name, definition):
    return client.register_scorer(
        {
            "experiment_id": experiment_id,
            "name": name,
            "serialized_scorer": definition,
        },
        config,
    )


def test_scorer_lifecycle_against_a_live_server(server, live_config):
    first = register(live_config, "exp-1", "Helpfulness", DEFINITION)
    assert first.experiment_id == "exp-1"
    assert first.version == 1
    assert first.creation_time == 1767225600001
    assert first.serialized_scorer == DEFINITION

    # Registering the same name again creates a new version of the same
    # scorer, matching the MLflow tracking store.
    second = register(live_config, "exp-1", "Helpfulness", UPDATED_DEFINITION)
    assert second.scorer_id == first.scorer_id
    assert second.version == 2

    latest = client.get_scorer("Helpfulness", live_config)
    assert latest.version == 2
    assert latest.serialized_scorer == UPDATED_DEFINITION

    original = client.get_scorer("Helpfulness", live_config, version=1)
    assert original.version == 1
    assert original.serialized_scorer == DEFINITION

    versions = client.list_scorer_versions("Helpfulness", live_config)
    assert [version.version for version in versions] == [2, 1]

    listed = client.list_scorers(live_config)
    assert [(scorer.scorer_id, scorer.version) for scorer in listed] == [
        (first.scorer_id, 2)
    ]

    register_request = server.requests[0]
    assert register_request["method"] == "POST"
    assert register_request["path"] == f"{client.API_PATH}/register"
    assert register_request["content_type"] == "application/json"
    assert register_request["body"]["experiment_id"] == "exp-1"

    client.delete_scorer("Helpfulness", live_config, version=1)
    assert [
        version.version
        for version in client.list_scorer_versions("Helpfulness", live_config)
    ] == [2]

    client.delete_scorer("Helpfulness", live_config)
    assert client.list_scorers(live_config) == ()


def test_duplicate_registration_maps_to_conflict(live_config):
    register(live_config, "exp-1", "Helpfulness", DEFINITION)

    with pytest.raises(MLflowAPIError) as excinfo:
        register(live_config, "exp-1", "helpfulness", DEFINITION)

    assert excinfo.value.error_kind == "conflict"
    assert excinfo.value.error_code == "RESOURCE_ALREADY_EXISTS"


def test_missing_scorer_maps_to_not_found(live_config):
    with pytest.raises(MLflowAPIError) as excinfo:
        client.get_scorer("Missing", live_config)

    assert excinfo.value.status_code == 404
    assert excinfo.value.error_kind == "not_found"
    assert "not found" in excinfo.value.message


def test_list_is_scoped_to_the_experiment(live_config):
    register(live_config, "exp-1", "Alpha", json.dumps({"name": "Alpha"}))
    register(live_config, "exp-1", "Beta", json.dumps({"name": "Beta"}))
    register(live_config, "exp-2", "Other", json.dumps({"name": "Other"}))

    assert [scorer.name for scorer in client.list_scorers(live_config)] == [
        "Alpha",
        "Beta",
    ]

    other_experiment = client.list_scorers(live_config, experiment_id="exp-2")
    assert [scorer.name for scorer in other_experiment] == ["Other"]


def test_list_filters_across_experiments(live_config):
    register(live_config, "exp-1", "Alpha", json.dumps({"name": "Alpha"}))
    register(live_config, "exp-2", "Beta", json.dumps({"name": "Beta"}))
    register(live_config, "exp-3", "Other", json.dumps({"name": "Other"}))

    scorers = client.list_scorers(live_config, experiment_ids=["exp-1", "exp-2"])

    assert sorted(scorer.name for scorer in scorers) == ["Alpha", "Beta"]


def test_deleting_a_missing_version_maps_to_not_found(live_config):
    register(live_config, "exp-1", "Helpfulness", DEFINITION)

    with pytest.raises(MLflowAPIError) as excinfo:
        client.delete_scorer("Helpfulness", live_config, version=99)

    assert excinfo.value.error_kind == "not_found"


def test_names_with_reserved_characters_round_trip(live_config):
    # Spaces, ``&``, and non-ASCII characters must survive the query-string
    # encoding the client applies to get/versions/list lookups.
    experiment_id = "exp 1 & 2"
    name = "Help fulness & co café"

    created = register(live_config, experiment_id, name, DEFINITION)

    fetched = client.get_scorer(name, live_config, experiment_id=experiment_id)
    assert fetched.scorer_id == created.scorer_id
    assert fetched.name == name
    assert fetched.experiment_id == experiment_id

    listed = client.list_scorers(live_config, experiment_id=experiment_id)
    assert [scorer.name for scorer in listed] == [name]

    versions = client.list_scorer_versions(
        name, live_config, experiment_id=experiment_id
    )
    assert [version.version for version in versions] == [1]

    client.delete_scorer(name, live_config, experiment_id=experiment_id)
    assert client.list_scorers(live_config, experiment_id=experiment_id) == ()
