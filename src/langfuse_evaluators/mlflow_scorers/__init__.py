"""MLflow scorer management.

This subpackage mirrors the Langfuse evaluator client: it registers,
lists, retrieves, versions, and deletes scorers through the MLflow REST
API under ``/api/3.0/mlflow/scorers``, and maps failures onto the same
stable error kinds.
"""

from .client import (
    API_PATH,
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
from .models import Scorer, scorers_from_list, validate_scorer_payload

__all__ = [
    "API_PATH",
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
    "scorers_from_list",
    "validate_scorer_payload",
]
