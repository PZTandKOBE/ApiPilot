"""Run request and response schemas.

Three contracts live in this module, and all three are load-bearing.

**1. Stable keys are echoed back; row UUIDs are never exposed.**
``run_scenarios`` / ``run_steps`` / ``run_assertions`` each carry an internal
UUID primary key *and* a stable key copied verbatim from the plan.  The frontend
joins on the stable key: ``frontend/src/utils/runState.ts`` matches rows by ``id``
equality with no positional fallback, and ``frontend/src/types/run.ts`` documents
it as "the join key, echoed back by the server".  So:

* ``RunScenarioResponse.id``  <- ``run_scenarios.scenario_key``
* ``RunStepResponse.id``      <- ``run_steps.step_key``
* ``RunAssertionResponse.id`` <- ``run_assertions.assertion_key``

The failure mode if this is broken is *silent*: re-key a response to the row
UUID and the detail page still renders, but its rows never update as events
arrive, and nothing raises.  ``backend/db/models/__init__.py`` already states
this rule for the models; this module is where it is honoured on the wire.

**2. ``test_runs.id`` is the one deliberate exception.**  ``test_runs`` has no
``public_id`` column, so its internal UUID *is* its external id.  It is URL
safe and the frontend treats it as opaque.  No other ``id`` in these payloads is
a UUID, and none of them is ``run_steps.id`` / ``run_assertions.id``.

**3. No model here may carry the *values* of a run's variables.**
``test_runs`` stores ``variable_keys`` (names, never values) and that is the
whole of what travels back.  Values arrive once, in ``RunCreateRequest.variables``,
and are not echoed: an environment can carry secrets, and a run history is not
the place to accumulate copies of them.  ``RunCreateRequest`` is the only model
in this package permitted a ``variables`` field, and it must never appear in a
``response_model=`` argument.

**4. The replay record mirrors the row, not the stream frame.**  The one event
model here, ``RunEventResponse``, returns a stored ``run_events`` row: the two
columns whose names the wire does not use are renamed (``event_type`` ->
``eventType``, ``created_at`` -> ``at``) and the ``payload`` column is handed
back as one object, exactly as stored.  ``frontend/src/types/run.ts`` declares
its eight stream events with that payload *spread* across the top level, and
this model deliberately does not do that: assembling a frame is the stream
phase's job, and a replay endpoint that re-derived one would be inventing a
shape the frontend contract has not fixed yet.  No value is recalculated either
way.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from backend.schemas.base import Schema
from backend.schemas.common import LocalizedText

__all__ = [
    "ApprovalStatus",
    "AssertionKind",
    "HttpMethod",
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
    "RunEventResponse",
    "RunEvidenceResponse",
    "RunFailureResponse",
    "RunListItem",
    "RunResponse",
    "RunScenarioResponse",
    "RunStatus",
    "RunStepResponse",
    "RunStepStatus",
    "RunSummaryResponse",
    "StepKind",
]

# --------------------------------------------------------------------------- #
# Enumerations
#
# Each mirrors a `as const` array in the frontend.  `Literal` rather than
# `StrEnum` so an unexpected value is a 422 at the edge instead of an object
# that stringifies to something plausible.
# --------------------------------------------------------------------------- #

RunStatus = Literal["queued", "running", "passed", "failed", "cancelled"]
RunStepStatus = Literal["pending", "running", "passed", "failed", "skipped"]
RunAssertionStatus = Literal["passed", "failed", "skipped"]
RiskLevel = Literal["low", "medium", "high"]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
StepKind = Literal["request", "extract", "assert"]
AssertionKind = Literal["status", "field", "schema", "header"]
ApprovalStatus = Literal["draft", "in_review", "approved", "rejected"]
PlanSource = Literal["generated", "handoff"]


# --------------------------------------------------------------------------- #
# Request: the plan tree
#
# `plan` arrives as the whole `TestPlan` from `frontend/src/types/agent.ts`,
# because the server has no plan of its own to look up -- plans are generated in
# the browser today.  These four models mirror that tree exactly; they are named
# `Plan*` rather than `Test*` to stay clear of the identically named SQLAlchemy
# classes in `backend.db.models`.
# --------------------------------------------------------------------------- #


class PlanStep(Schema):
    """One step of a plan. Mirrors ``TestStep`` in ``types/agent.ts``."""

    id: str
    index: int
    kind: StepKind
    description: LocalizedText
    endpoint_id: str | None
    method: HttpMethod | None
    path: str | None
    produces: str | None = Field(
        default=None, description="Variable this step produces, for `extract` steps."
    )
    consumes: list[str] = Field(default_factory=list)


class PlanAssertion(Schema):
    """One assertion as written. Mirrors ``TestAssertion`` in ``types/agent.ts``."""

    id: str
    kind: AssertionKind
    target: str = Field(description="Dotted path within the response, e.g. `body.token`.")
    expected: str
    description: LocalizedText


class PlanScenario(Schema):
    """One scenario as written. Mirrors ``TestScenario`` in ``types/agent.ts``."""

    id: str
    index: int
    name: LocalizedText
    description: LocalizedText
    risk_level: RiskLevel
    steps: list[PlanStep] = Field(default_factory=list)
    expected: LocalizedText
    assertions: list[PlanAssertion] = Field(default_factory=list)


class PlanPayload(Schema):
    """The whole plan, as submitted. Mirrors ``TestPlan`` in ``types/agent.ts``.

    ``generated_at`` has no column to land in -- ``test_plans`` stores
    ``created_at`` / ``updated_at`` as database defaults, so the moment a plan
    was generated in the browser is not recoverable.  It is validated here
    because a malformed timestamp is still a malformed request, and dropped at
    materialisation time.
    """

    id: str
    project_id: str
    spec_id: str
    name: LocalizedText
    goal: LocalizedText
    risk_level: RiskLevel
    status: ApprovalStatus
    scenarios: list[PlanScenario] = Field(default_factory=list)
    source: PlanSource
    generated_at: datetime
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = Field(
        default=None, description="Free text typed by the reviewer; never generated."
    )


class RunCreateRequest(Schema):
    """The body of ``POST /api/projects/{project_id}/runs``.

    Field-for-field mirror of ``CreateRunInput`` in ``frontend/src/services/run.ts``.
    Aliases are written out explicitly rather than generated, so that the eight
    names can be diffed against that file by eye -- this is the one request in
    the service whose shape is owned by another repository.

    **The only model in this package allowed a ``variables`` field.**  Its values
    are the reason ``RunResponse`` has none: they are secrets in flight and are
    never echoed back.  See the module docstring.
    """

    model_config = ConfigDict(alias_generator=None)

    project_id: str = Field(alias="projectId")
    plan_id: str = Field(alias="planId")
    plan: PlanPayload
    spec_id: str = Field(alias="specId")
    spec_document: str = Field(
        alias="specDocument",
        description="The OpenAPI document's original text, as stored.",
    )
    environment_id: str = Field(alias="environmentId")
    variables: dict[str, str] = Field(
        alias="variables",
        description="Names to values for this run. Write-only: never echoed back.",
    )
    base_url: str = Field(alias="baseUrl")


# --------------------------------------------------------------------------- #
# Response: records
# --------------------------------------------------------------------------- #


class RunFailureResponse(Schema):
    """Why something failed, in both registers. Mirrors ``RunFailure``.

    Neither field has a column of its own.  ``message`` is derived from
    ``error_code`` via a mapping the API layer owns; ``detail`` is
    ``error_message`` and is shown verbatim.
    """

    message: LocalizedText
    detail: str | None = None


class RunEvidenceResponse(Schema):
    """One artifact a step left behind. Mirrors ``AgentEvidence``.

    ``run_evidence`` also carries ``evidence_type`` and ``content``.  Neither is
    in the frontend type, so neither is in the payload -- an unconsumed field is
    a field nobody notices going stale.
    """

    label: LocalizedText
    value: str


class RunAssertionResponse(Schema):
    """One assertion as it came out. Mirrors ``RunAssertion``."""

    id: str = Field(description="`run_assertions.assertion_key` -- the plan's assertion id.")
    scenario_id: str = Field(description="The parent's `scenario_key`.")
    step_id: str | None = Field(
        default=None, description="The joined `run_steps.step_key`, when it belongs to a step."
    )
    kind: AssertionKind
    target: str
    expected: str
    actual: str | None = None
    status: RunAssertionStatus
    description: LocalizedText


class RunStepResponse(Schema):
    """One step as it came out. Mirrors ``RunStep``."""

    id: str = Field(description="`run_steps.step_key` -- the plan's step id.")
    scenario_id: str = Field(description="The parent's `scenario_key`.")
    index: int = Field(description="`run_steps.sort_order`.")
    kind: StepKind = Field(description="`run_steps.step_type`.")
    description: LocalizedText
    endpoint_id: str | None = None
    method: HttpMethod | None = None
    path: str | None = None
    status: RunStepStatus
    duration_ms: int | None = None
    failure: RunFailureResponse | None = None
    evidence: list[RunEvidenceResponse] = Field(default_factory=list)


class RunScenarioResponse(Schema):
    """One scenario as it came out, with its rows in run order. Mirrors ``RunScenario``."""

    id: str = Field(description="`run_scenarios.scenario_key` -- the plan's scenario id.")
    index: int = Field(description="`run_scenarios.sort_order`.")
    name: LocalizedText
    risk_level: RiskLevel
    status: RunStepStatus = Field(description="Scenarios reuse the step status vocabulary.")
    steps: list[RunStepResponse] = Field(default_factory=list)
    assertions: list[RunAssertionResponse] = Field(default_factory=list)


class RunSummaryResponse(Schema):
    """How much of the plan actually ran, and how much of it held.

    Mirrors ``RunSummary``.  Computed per request, not stored: there is no
    summary column, and the counts are a ``GROUP BY`` over ``run_steps`` joined
    through ``run_scenarios`` because ``run_steps`` carries no ``run_id``.
    """

    scenarios: int
    steps: int
    assertions: int
    passed_steps: int
    failed_steps: int
    passed_assertions: int
    failed_assertions: int


# --------------------------------------------------------------------------- #
# Response: the run itself
# --------------------------------------------------------------------------- #


class RunResponse(Schema):
    """A run's identity and outcome, without its steps. Mirrors ``TestRun``.

    Carries ``variable_keys`` and deliberately no ``variables``: see the module
    docstring, rule 3.
    """

    id: str = Field(
        description="`test_runs.id` -- the one place a row UUID is the external id, "
        "because `test_runs` has no `public_id` column.",
    )
    project_id: str
    plan_id: str
    plan_name: LocalizedText = Field(
        description="Copied at creation, so a renamed plan does not rewrite history."
    )
    spec_id: str
    environment_id: str = Field(
        description="Recorded rather than derived: re-reading the current environment "
        "would relabel a Staging run as Production the moment the user switches.",
    )
    base_url: str
    variable_keys: list[str] = Field(
        default_factory=list,
        description="Which variables the run was given, by name only. Never the values.",
    )
    status: RunStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = Field(
        default=None, description="Computed from `started_at` / `finished_at`; not a column."
    )
    failure: RunFailureResponse | None = None
    summary: RunSummaryResponse


class RunListItem(RunResponse):
    """A run as it appears in ``GET /api/projects/{project_id}/runs``.

    **The same shape as ``RunResponse``, by design.**  ``upsertRun`` in
    ``frontend/src/stores/runs.ts`` writes all four paths -- list item, creation
    response, detail snapshot, cancel response -- into one array keyed by ``id``.
    Any field that differs between them vanishes from whichever row the other
    path last touched.
    """


class RunCancelResponse(RunResponse):
    """The run as it stands after a cancel request. Mirrors ``cancelRun()``'s
    ``Promise<TestRun>``, which returns the current state rather than a receipt."""


class RunDetailResponse(Schema):
    """A run together with everything needed to draw it. Mirrors ``RunDetail``.

    ``last_seq`` is the reconnect contract: the client sets its high-water mark
    from it and drops any event at or below it, which is what makes a snapshot
    plus the tail of the stream equivalent to having been connected throughout.
    """

    run: RunResponse
    scenarios: list[RunScenarioResponse] = Field(default_factory=list)
    last_seq: int = Field(
        default=0,
        description="Highest `run_events.seq` for this run; 0 when none have been written.",
    )

# --------------------------------------------------------------------------- #
# Response: the event replay record
# --------------------------------------------------------------------------- #


class RunEventResponse(Schema):
    """One persisted event, as ``GET /api/runs/{run_id}/events`` returns it.

    **A row, not a stream frame.**  The eight ``RunEvent`` members in
    ``frontend/src/types/run.ts`` are ``{ type, runId, seq, at }`` plus that
    event's own fields, spread flat; this model returns the ``payload`` column as
    one object instead.  Assembling a frame is the stream phase's business, and a
    replay endpoint that guessed at one would be inventing a shape nobody has
    agreed to -- while a client that wants the frame still has everything it
    needs, because the payload comes back whole and unmodified.

    ``eventType`` carries ``run_events.event_type`` and ``at`` carries
    ``run_events.created_at``: the same renaming every other model in this package
    performs, and the reason one object here holds both the database's names and
    the frontend's.

    ``event_type`` is a ``str`` rather than a ``Literal`` over the eight known
    names.  The vocabulary is closed in the frontend, but the column has no CHECK
    behind it and this service is not its only possible writer, so a Literal here
    would turn one unknown row into a 500 that hides the whole history of an
    otherwise readable run.  The client's ``isRunEvent`` guard is where a name it
    does not know is dropped, and that is a decision for the reader.

    No ``id``.  ``run_events.id`` is an internal UUID and, like every other key of
    the run subtree, it does not leave the process.  An event is identified by
    ``(runId, seq)`` -- unique by constraint, and the pair ``lastSeq`` is already
    expressed in.
    """

    run_id: str = Field(
        description="The run's external id. `test_runs.id` is the one row key that is "
        "its own public id, and this is the same value the request path carried."
    )
    seq: int = Field(description="`run_events.seq`: starts at 1 and is dense within a run.")
    at: datetime = Field(
        description="`run_events.created_at`: when the server observed the event."
    )
    event_type: str = Field(
        description="`run_events.event_type`. One of the eight names the frontend declares "
        "in `RUN_EVENT_NAMES`; this service writes `run.cancelled`."
    )
    payload: dict[str, Any] = Field(
        description="`run_events.payload`, returned exactly as stored."
    )
