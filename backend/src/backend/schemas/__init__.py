"""Pydantic schemas: the HTTP boundary.

Re-exported here so callers write ``from backend.schemas import RunResponse``
rather than reaching into submodules.  ``backend/db/__init__.py`` is empty,
which means ``from backend.db import User`` silently yields nothing useful; this
package does not repeat that.
"""

from backend.schemas.auth import (
    AuthConfigResponse,
    AuthProviderStatus,
    CurrentUserResponse,
)
from backend.schemas.base import Schema
from backend.schemas.common import (
    ErrorResponse,
    LiteralMessage,
    LocalizedMessage,
    LocalizedText,
)
from backend.schemas.report import RunReportResponse
from backend.schemas.run import (
    ApprovalStatus,
    AssertionKind,
    HttpMethod,
    PlanAssertion,
    PlanPayload,
    PlanScenario,
    PlanSource,
    PlanStep,
    RiskLevel,
    RunAssertionResponse,
    RunCancelResponse,
    RunCreateRequest,
    RunDetailResponse,
    RunEvidenceResponse,
    RunFailureResponse,
    RunListItem,
    RunResponse,
    RunScenarioResponse,
    RunStatus,
    RunStepResponse,
    RunStepStatus,
    RunSummaryResponse,
    StepKind,
)

__all__ = [
    "ApprovalStatus",
    "AuthConfigResponse",
    "AuthProviderStatus",
    "CurrentUserResponse",
    "AssertionKind",
    "ErrorResponse",
    "HttpMethod",
    "LiteralMessage",
    "LocalizedMessage",
    "LocalizedText",
    "PlanAssertion",
    "PlanPayload",
    "PlanScenario",
    "PlanSource",
    "PlanStep",
    "RiskLevel",
    "RunAssertionResponse",
    "RunCancelResponse",
    "RunCreateRequest",
    "RunDetailResponse",
    "RunEvidenceResponse",
    "RunFailureResponse",
    "RunListItem",
    "RunReportResponse",
    "RunResponse",
    "RunScenarioResponse",
    "RunStatus",
    "RunStepResponse",
    "RunStepStatus",
    "RunSummaryResponse",
    "Schema",
    "StepKind",
]
