"""MLflow scorer management.

This subpackage mirrors the Langfuse evaluator client: it registers,
lists, retrieves, versions, and deletes scorers through the MLflow REST
API under ``/api/3.0/mlflow/scorers``, and maps failures onto the same
stable error kinds.

Only the client operations, the error types, and the ``Scorer`` model are
re-exported here; transport details stay on the module that owns them
(``client.API_PATH``, ``models.validate_scorer_payload``,
``models.scorers_from_list``).
"""

from .client import (
    delete_scorer,
    get_scorer,
    list_scorer_versions,
    list_scorers,
    register_scorer,
)
from .errors import (
    MLflowAPIError,
    MLflowError,
    MLflowResponseError,
    MLflowTransportError,
)
from .models import Scorer

__all__ = [
    "MLflowAPIError",
    "MLflowError",
    "MLflowResponseError",
    "MLflowTransportError",
    "Scorer",
    "delete_scorer",
    "get_scorer",
    "list_scorer_versions",
    "list_scorers",
    "register_scorer",
]
