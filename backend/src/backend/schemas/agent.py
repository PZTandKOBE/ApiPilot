"""Agent task request and response schemas.

Phase 8.2 Step 2.  The agent pipeline's wire contract, kept in its own module
for the same reason run.py has one: the shapes are the API, and the models that
happen to be shared with the run side (PlanPayload and its tree) stay where the
run side already reads them.

Three rules are inherited from the frozen contract rather than invented here:

* **The task id is a UUID, and that is the documented exception.**  Like
  test_runs, `agent_tasks` has no `public_id` column, so its internal key
  *is* its external id.  Everything else the agent returns is a stable key
  (`plan_...`, `scenario_...`, `spec_...`).
* **Values never travel back.**  `AgentTaskCreateRequest.variables` is the only
  place a run-time value may appear, it is write-only, and it must never appear
  in a `response_model` argument -- exactly the rule `RunCreateRequest`
  carries.  There is no field to echo it into, and that is deliberate.
* **A failed task still answers with a task.**  The failure vocabulary mirrors
  `frontend/src/services/agentError.ts` so the browser can keep mapping codes
  to sentences it already ships.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Any

from pydantic import Field

from backend.schemas.base import Schema
from backend.schemas.common import LocalizedText

__all__ = [
    "AgentAssertionResponse",
    "AgentAuthenticationResponse",
    "AgentDependencyResponse",
    "AgentEndpointResponse",
    "AgentEvidenceResponse",
    "AgentFindingResponse",
    "AgentPlanResponse",
    "AgentResourceResponse",
    "AgentRiskResponse",
    "AgentScenarioResponse",
    "AgentStepResponse",
    "AgentTaskCreateRequest",
    "AgentTaskFailure",
    "AgentTaskResponse",
    "AgentTaskStatus",
    "AgentUnderstandingResponse",
    "AgentVerdict",
]

AgentTaskStatus = Literal["pending", "analyzing", "completed", "failed"]
"""The four states `agent_tasks.status` may hold.  Not a new vocabulary: it is
the one the schema document fixes (`backend/dosc`) and the one the step-2 state
machine walks."""

AgentVerdict = Literal["succeeded", "failed", "skipped"]
"""Mirrors AgentActionResult in frontend/src/types/agent.ts."""


class AgentTaskCreateRequest(Schema):
    """The body of `POST /api/projects/{project_id}/agent/tasks`.

    Field-for-field the frozen `AgentTaskInput`: the project and the
    environment say *where*, the document says *what*, and the prompt says *what
    for*.  `projectId` appears in the path as well; the two must agree, which
    is the same rule the run create enforces with `_check_identity`.

    `specDocument` is the document's original text, not a summary of it: the
    understanding is recomputed from it on every run, so nothing derived has to
    be trusted or stored.
    """

    project_id: str = Field(alias="projectId")
    spec_id: str = Field(
        alias="specId",
        description="spec_ + the document's slug. Re-derived and checked server-side.",
    )
    spec_document: str = Field(
        alias="specDocument",
        description="The OpenAPI document's original text, as stored.",
    )
    environment_id: str | None = Field(default=None, alias="environmentId")
    prompt: str = Field(description="What the user asked the agent for.")
    variables: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Run-time values, accepted for contract fidelity and write-only. "
            "They are scanned for leaks and then dropped: nothing persists them."
        ),
    )
    regenerate: bool = Field(
        default=False,
        description=(
            "False is the ordinary first-generation contract: an existing plan id "
            "is refused with 409 plan-exists. True creates a new version in the "
            "same project/document series and never overwrites the old plan."
        ),
    )


class AgentAssertionResponse(Schema):
    """One assertion, as stored.  Mirrors TestAssertion in types/agent.ts."""

    id: str = Field(description="test_assertions.assertion_key -- the plan's assertion id.")
    kind: str = Field(description="test_assertions.assertion_type.")
    target: str
    expected: str = Field(description="`expected_value`, stored as the string it is.")
    description: LocalizedText | None = None
    step_id: str | None = Field(
        default=None,
        description=(
            "test_steps.step_key of the assert step this assertion reads, or null "
            "for a plan-written-before binding.  Round-trips the plan so a run "
            "created from it judges each group against its own response."
        ),
    )


class AgentStepResponse(Schema):
    """One step, as stored.  Mirrors TestStep in types/agent.ts.

    `method` and `path` are read back out of `test_steps.config`, where a
    request step's target has lived since Phase 8.2 Step 1 -- the plan-side table
    has no columns for them by design.  `endpoint_id` is null for the same
    reason it is null in the database: the plan's endpoint id is the frontend's
    own string (`ep_post_orders`), the column is a foreign key to
    `api_endpoints`, and those rows have never been materialised.
    """

    id: str = Field(description="test_steps.step_key -- the plan's step id.")
    index: int = Field(description="test_steps.sort_order.")
    kind: str = Field(description="test_steps.step_type: request / extract / assert.")
    description: LocalizedText
    endpoint_id: str | None = None
    method: str | None = None
    path: str | None = None
    produces: str | None = None
    body: Any | None = None
    body_present: bool = False
    consumes: list[str] = Field(default_factory=list)


class AgentScenarioResponse(Schema):
    """One scenario with its rows, in plan order.  Mirrors TestScenario."""

    id: str = Field(description="test_scenarios.scenario_key.")
    index: int = Field(description="test_scenarios.sort_order.")
    name: LocalizedText
    description: LocalizedText | None = None
    risk_level: str
    steps: list[AgentStepResponse] = Field(default_factory=list)
    expected: LocalizedText | None = None
    assertions: list[AgentAssertionResponse] = Field(default_factory=list)


class AgentPlanResponse(Schema):
    """The whole plan a task produced, read back from the plan-side tables.

    **The tree, not a summary.**  The console reviews a plan by rendering its
    scenarios, steps and assertions, and a plan read surface that answered with
    counts would leave the browser to invent the rows it draws -- which is the
    one thing this integration must not do.

    Field for field the plan the agent wrote, and therefore the frontend's
    `TestPlan`, with two documented readings:

    * `generated_at` is `test_plans.created_at`.  An agent-produced plan is
      written in the transaction that produced it, so for this path the storage
      time *is* the generation time; the payload's own `generatedAt` has no
      column (contract section 6.1).
    * `assertions` are ordered by key, not by declaration: `test_assertions`
      has no `sort_order` column, and the run read path made the same choice.
    """

    id: str = Field(description="test_plans.public_id -- the plan's stable key.")
    project_id: str
    spec_id: str
    version: int = Field(
        default=1,
        description=(
            "test_plans.version. The first plan for a document is version 1; each "
            "regeneration creates the next version under a new public id."
        ),
    )
    is_current: bool = Field(
        default=True,
        description=(
            "Whether this is the highest version for its project/document. "
            "Currentness is independent of approval: a newer draft is current "
            "while the older approved version remains available."
        ),
    )
    run_count: int = Field(
        default=0,
        description="Number of test_runs whose plan_id points at this version.",
    )
    name: LocalizedText
    goal: LocalizedText | None = Field(
        default=None, description="`test_plans.description`, the only prose column."
    )
    risk_level: str
    status: str = Field(description="Always draft from this pipeline.")
    scenarios: list[AgentScenarioResponse] = Field(default_factory=list)
    source: str
    generated_at: datetime
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None


# --------------------------------------------------------------------------- #
# The understanding -- what the agent read out of the document
#
# Returned by the create call and by nothing else: the understanding is a pure
# function of the document and is never persisted (contract section 4.2), so
# there is no row to read it back from later.  The models mirror
# `ApiUnderstanding` in frontend/src/types/agent.ts field for field, which is
# what lets the console render the analysis it was shown.
# --------------------------------------------------------------------------- #


class AgentEndpointResponse(Schema):
    """One operation the agent read.  Mirrors ApiEndpoint."""

    id: str
    method: str
    path: str
    resource_id: str
    summary: LocalizedText
    requires_auth: bool
    path_params: list[str] = Field(default_factory=list)
    required_body_props: list[str] = Field(default_factory=list)
    constrained_body_props: list[str] = Field(default_factory=list)
    response_statuses: list[int] = Field(default_factory=list)
    response_props: list[str] = Field(default_factory=list)


class AgentResourceResponse(Schema):
    id: str
    name: str
    endpoint_ids: list[str] = Field(default_factory=list)


class AgentAuthenticationResponse(Schema):
    scheme: str
    scheme_name: str | None = None
    header_name: str | None = None
    token_source_endpoint_id: str | None = None
    token_field: str | None = None
    protected_endpoint_count: int


class AgentDependencyResponse(Schema):
    id: str
    from_endpoint_id: str
    to_endpoint_id: str
    kind: str
    binding: str
    rationale: LocalizedText


class AgentRiskResponse(Schema):
    id: str
    level: str
    category: str
    title: LocalizedText
    detail: LocalizedText
    related_endpoint_ids: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)


class AgentEvidenceResponse(Schema):
    label: LocalizedText
    value: str


class AgentFindingResponse(Schema):
    id: str
    action: LocalizedText
    decision_summary: LocalizedText
    result: str = Field(description="succeeded / failed / skipped.")
    evidence: list[AgentEvidenceResponse] = Field(default_factory=list)
    at: str


class AgentUnderstandingResponse(Schema):
    spec_id: str
    endpoints: list[AgentEndpointResponse] = Field(default_factory=list)
    resources: list[AgentResourceResponse] = Field(default_factory=list)
    authentication: AgentAuthenticationResponse
    dependencies: list[AgentDependencyResponse] = Field(default_factory=list)
    risks: list[AgentRiskResponse] = Field(default_factory=list)
    findings: list[AgentFindingResponse] = Field(default_factory=list)
    analyzed_at: str


class AgentTaskFailure(Schema):
    """Why the agent stopped, in both registers.

    `message` mirrors `RunFailureResponse`: a `LocalizedText` the frontend
    can render, built from a key that already exists in its dictionary.
    `detail` is the machine-language cause, shown exactly as received.

    A failure that happened before the plan existed is only ever reported on the
    response that caused it: `agent_tasks` has no error column, so
    `GET /api/agent/tasks/{id}` answers a failed task with the status and
    nothing more.  That gap is recorded in the contract, not papered over.
    """

    code: str
    message: LocalizedText
    detail: str | None = None


class AgentTaskResponse(Schema):
    """A task, the plan it produced, and nothing else.

    Mirrors the shape of a run response deliberately: a stable id, a status, the
    frozen copy of what the user asked for (`prompt`), timestamps, and one
    optional failure.  There is no `variables` field and no place for one --
    see the module docstring.
    """

    id: str = Field(description="agent_tasks.id. The one row UUID that is an external id.")
    project_id: str
    spec_id: str
    environment_id: str | None = None
    prompt: str
    status: AgentTaskStatus
    created_at: datetime
    updated_at: datetime
    plan: AgentPlanResponse | None = Field(
        default=None, description="The stored plan tree, once the pipeline has written it."
    )
    understanding: AgentUnderstandingResponse | None = Field(
        default=None,
        description=(
            "What the agent read, on the response that produced it. Null when a task is "
            "read back: the understanding is never persisted, so there is nothing to return."
        ),
    )
    failure: AgentTaskFailure | None = Field(
        default=None,
        description=(
            "Reserved, and always null today: a pipeline refusal is answered with the error "
            "envelope rather than a task body, and agent_tasks has no column for a reason. "
            "Recorded in the contract as gap G4."
        ),
    )
