"""Server-side agent tasks: the lifecycle around the deterministic pipeline.

Phase 8.2 Step 2.  The stages themselves are pure functions in
backend.services.agent_plan; what lives here is everything they must not know
about -- the database, the task's state machine, the plan's persistence and the
rule that a plan id already in use is refused rather than overwritten.

One task, in order:

    create   -> checks, lookups, the spec row, agent_tasks(status=pending)
                committed before anything can fail, so a failure is recorded
    process  -> analyzing
                parse -> analyze -> generate -> validate
                persist (the four plan-side tables, in one transaction)
                completed
                any refusal instead -> failed

Two properties are the point of the step:

* **Validation sits between generation and persistence, and persistence is the
  only writer.**  parse, analyze and generate return values and touch no table;
  `_persist` is called once, after `validate_plan` has accepted the plan.  A
  refused plan leaves the four plan tables exactly as it found them.
* **A failure is a status, not a stack trace.**  Test 7's contract is "no rows
  and a failed task", and it is enforced by rolling the write transaction back
  and committing the status change in its own.

Where the sharing goes: `_get_or_create_spec`, `_lookup_project`,
`_lookup_environment` and `_create_plan_tree` are imported from
backend.services.runs.  They are private to the *service package*, not to the
module -- api_specs and the four plan-side tables each have exactly one writer,
and a second copy of the identity rule or of the plan mapping is how two
implementations of one contract start to disagree.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import AppError
from backend.db.models.agent import AgentTask
from backend.db.models.project import ApiSpec
from backend.schemas.agent import (
    AgentAssertionResponse,
    AgentAuthenticationResponse,
    AgentDependencyResponse,
    AgentEndpointResponse,
    AgentEvidenceResponse,
    AgentFindingResponse,
    AgentPlanResponse,
    AgentResourceResponse,
    AgentRiskResponse,
    AgentScenarioResponse,
    AgentStepResponse,
    AgentTaskCreateRequest,
    AgentTaskResponse,
    AgentUnderstandingResponse,
)
from backend.schemas.agent_audit import (
    AgentAuditStageResponse,
    AgentTaskAuditResponse,
    AgentUsageCounts,
    AgentUsageResponse,
)
from backend.services import agent_analyzer, agent_audit, agent_plan
from backend.services.agent_plan import PlanInvalid, PlanPipelineError
from backend.services.runs import (
    _create_plan_tree,
    _get_or_create_spec,
    _lookup_environment,
    _lookup_project,
)
from backend.services.spec_identity import derive_spec_identity, probe_document, spec_id_for

__all__ = ["create_task", "get_task", "process_task", "start_task"]

logger = logging.getLogger(__name__)

# The failure vocabulary the frontend's dictionary can actually render.  Codes
# outside AgentErrorCode (frontend/src/services/agentError.ts) exist here too --
# plan-exists and task-not-found have no frontend code yet -- and each is paired
# with the closest sentence the dictionary does have.  The gap is recorded in
# docs/agent-pipeline-contract.md rather than papered over with a generic
# sentence that hides which thing went wrong.
_NOT_FOUND = "console.runs.errors.notFound"
_PARSE_FAILED = "console.aiTest.errors.parseFailed"
_UNSUPPORTED_FORMAT = "console.aiTest.errors.unsupportedFormat"
_NO_ENDPOINTS = "console.aiTest.errors.noEndpoints"
_ANALYZE_FAILED = "console.aiTest.errors.analyzeFailed"
_GENERATE_FAILED = "console.aiTest.errors.generateFailed"

_STAGE_MESSAGE_KEYS: dict[str, str] = {
    "parse-failed": _PARSE_FAILED,
    "unsupported-format": _UNSUPPORTED_FORMAT,
    "no-endpoints": _NO_ENDPOINTS,
    "analyze-failed": _ANALYZE_FAILED,
    "generate-failed": _GENERATE_FAILED,
    "plan-invalid": _GENERATE_FAILED,
}

_PENDING = "pending"
_ANALYZING = "analyzing"
_COMPLETED = "completed"
_FAILED = "failed"


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


def _stage_error(code: str, detail: str, *, status_code: int = 422) -> AppError:
    """An error envelope for a pipeline refusal.

    `params` carries `detail` only for the key that interpolates it: the
    frontend's sentence for a parse failure reads "could not be parsed:
    {detail}", and passing params where a sentence has no placeholder is how an
    unused value ends up looking load-bearing.
    """
    message_key = _STAGE_MESSAGE_KEYS.get(code, _GENERATE_FAILED)
    params = {"detail": detail} if message_key == _PARSE_FAILED else None

    return AppError(
        status_code,
        code=code,
        message_key=message_key,
        params=params,
        details={"detail": detail},
    )


def _request_error(code: str, status_code: int, **details: Any) -> AppError:
    """A refusal of the request itself, before any task exists."""
    return AppError(
        status_code,
        code=code,
        message_key=_GENERATE_FAILED,
        details=details or None,
    )


def _task_not_found(task_id: str) -> AppError:
    return AppError(
        404,
        code="task-not-found",
        message_key=_NOT_FOUND,
        details={"taskId": task_id},
    )


@dataclass
class _Progress:
    """What the pipeline has reached, for the audit's failure record.

    The stage is tracked here as well as in the table because `_fail` rolls the
    transaction back before it writes anything: whatever the audit row held
    mid-flight is gone by then, and the stage that failed is the one fact the
    failure record cannot do without.  The artifacts are kept for the same
    reason -- a task that fails at validation is exactly when "what did the model
    understand, and what did it design" matters most.
    """

    stage: str = "pending"
    analysis: agent_analyzer.AnalysisOutcome | None = None
    understanding: dict[str, Any] | None = None
    plan: agent_analyzer.PlanOutcome | None = None
    design: dict[str, Any] | None = None
    forbidden: tuple[str, ...] = ()


def _task_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# create
# --------------------------------------------------------------------------- #


async def create_task(
    session: AsyncSession, *, project_id: str, payload: AgentTaskCreateRequest
) -> uuid.UUID:
    """Record the request as a task in `pending`, and commit it.

    Everything a run needs to fail before its first statement happens here too:
    the two identity agreements, the project and environment lookups, the
    document's identity, and the conflict rule.  A request that is going to be
    refused should not leave a task behind -- except for the failures that only
    exist *because* a task exists, which is why this commits the row before the
    pipeline runs.
    """
    if payload.project_id != project_id:
        raise _request_error(
            "project-mismatch", 400, expected=project_id, received=payload.project_id
        )

    facts = probe_document(payload.spec_document)
    identity = derive_spec_identity(
        spec_document=payload.spec_document, spec_id=payload.spec_id, facts=facts
    )

    if identity.verified and spec_id_for(identity.slug) != payload.spec_id:
        raise _request_error(
            "spec-mismatch",
            400,
            expected=spec_id_for(identity.slug),
            received=payload.spec_id,
        )

    project = await _lookup_project(session, project_id)

    environment_id: uuid.UUID | None = None
    if payload.environment_id:
        environment = await _lookup_environment(session, project.id, payload.environment_id)
        environment_id = environment.id

    spec = await _get_or_create_spec(
        session,
        project_id=project.id,
        spec_document=payload.spec_document,
        facts=facts,
        identity=identity,
    )

    # The conflict rule, checked before the task exists.  A plan id is derived
    # from the document's slug, so a second prompt against the same document
    # names the same plan -- and a different prompt's result must never quietly
    # replace the first one's.  Versioning and regeneration are a later phase;
    # today the answer is a refusal.
    if await _find_plan(session, project.id, spec.slug) is not None:
        raise _request_error("plan-exists", 409, planId=f"plan_{spec.slug}")

    task = AgentTask(
        project_id=project.id,
        spec_id=spec.id,
        environment_id=environment_id,
        prompt=payload.prompt,
        status=_PENDING,
    )
    session.add(task)
    await session.flush()

    # The audit opens in the same commit as the task, so the two either both
    # exist or neither does: a task that fails on its first statement still has
    # somewhere to say where it failed (Phase 8.4 Step 1).
    await agent_audit.create(session, task_id=task.id)
    await session.commit()

    return task.id


async def start_task(
    session: AsyncSession, *, project_id: str, payload: AgentTaskCreateRequest
) -> AgentTaskResponse:
    """The route's whole job: create the task, then run it."""
    task_id = await create_task(session, project_id=project_id, payload=payload)

    return await process_task(session, task_id=task_id, variables=payload.variables)

# --------------------------------------------------------------------------- #
# process
# --------------------------------------------------------------------------- #


async def process_task(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    variables: Mapping[str, str] | None = None,
) -> AgentTaskResponse:
    """Walk one task from `pending` to `completed` or `failed`.

    `variables` are the run-time values from the request.  They are read once,
    for the leak scan, and never written: agent_tasks has no column for them and
    a plan may not contain them (contract section 3.1, I4).
    """
    row = await _load_task(session, task_id)
    if row is None:
        raise _task_not_found(str(task_id))

    if row["status"] != _PENDING:
        raise _request_error("task-not-pending", 409, taskId=str(task_id), status=row["status"])

    await _set_status(session, task_id, _ANALYZING)
    await agent_audit.set_stage(session, task_id=task_id, stage="analyzing")
    await session.commit()

    progress = _Progress(stage="analyzing")

    try:
        # Read before the pipeline runs: the leak scan's values are needed by the
        # validator *and* by the audit, which removes them from anything it keeps.
        forbidden = await _forbidden_values(session, row, variables or {})
        progress.forbidden = tuple(forbidden)
        analysis, planned = await _generate(
            session, row, task_id=task_id, progress=progress, forbidden=forbidden
        )
        await agent_audit.set_stage(session, task_id=task_id, stage="validate")
        agent_plan.validate_plan(
            planned.plan,
            project_id=row["project_public_id"],
            spec_id=spec_id_for(row["slug"]),
            expected_plan_id=f"plan_{row['slug']}",
            forbidden_values=forbidden,
        )
    except PlanInvalid as invalid:
        await _fail(session, task_id, invalid, invalid.issues, progress=progress)
        raise _stage_error(invalid.code, invalid.detail) from invalid
    except PlanPipelineError as refusal:
        await _fail(session, task_id, refusal, progress=progress)
        raise _stage_error(refusal.code, refusal.detail) from refusal

    await agent_audit.set_stage(session, task_id=task_id, stage="persist")
    await _persist(session, row=row, plan=planned.plan, task_id=task_id)
    await _set_status(session, task_id, _COMPLETED)
    await agent_audit.complete(session, task_id=task_id)
    await session.commit()

    # The plan comes back out of the database -- the caller reviews the rows the
    # server wrote, not the object the pipeline happened to hold.  The
    # understanding has no row to come back from, so it travels in memory and
    # only on this response.
    return await _response(
        session,
        task_id,
        understanding=_understanding_response(
            analysis.understanding, spec_id=spec_id_for(row["slug"])
        ),
    )


async def _generate(
    session: AsyncSession,
    row: Mapping[str, Any],
    *,
    task_id: uuid.UUID,
    progress: _Progress,
    forbidden: Sequence[str] = (),
) -> tuple[agent_analyzer.AnalysisOutcome, agent_analyzer.PlanOutcome]:
    """parse -> analyze -> generate, over the document the spec row holds.

    The document is read back from `api_specs.content` rather than carried in
    memory: the task is anchored to the row it was created against, and a
    process that starts later has nothing else to go on.

    Both artifacts come back because both are needed and only one of them is
    stored: the plan becomes rows, the understanding becomes the response.
    """
    spec = await session.get(ApiSpec, row["spec_id"])
    if spec is None:  # pragma: no cover - the FK is NO ACTION, so it cannot vanish
        raise PlanPipelineError("parse-failed", "the specification row is gone")

    progress.stage = "parse"
    await agent_audit.set_stage(session, task_id=task_id, stage="parse")

    document = agent_plan.decode_document(spec.content)
    parsed = agent_plan.parse_document(
        document,
        project_id=row["project_public_id"],
        spec_id=spec_id_for(spec.slug),
        slug=spec.slug,
        filename=spec.filename or spec.name,
        source=spec.source or "upload",
    )
    # The one model-shaped step.  Which implementation runs is decided by
    # AGENT_ANALYZER (Phase 8.3 Step 1): the rule engine, or DeepSeek behind two
    # layers of validation.  Everything after this line is deterministic again.
    progress.stage = "analyze"
    analysis = await agent_analyzer.analyze_detailed(
        parsed, task=row["prompt"], document=document
    )
    progress.analysis = analysis
    progress.understanding = _understanding_payload(
        analysis.understanding, spec_id=spec_id_for(row["slug"])
    )
    await _record_analysis(
        session,
        task_id=task_id,
        analysis=analysis,
        understanding=progress.understanding,
        forbidden=forbidden,
    )

    # The second model-shaped step, and the last one: from here on the plan is
    # data the deterministic validator and the executor own.  AGENT_PLANNER
    # selects the rule engine or DeepSeek (Phase 8.3 Step 2).
    progress.stage = "generate"
    await agent_audit.set_stage(session, task_id=task_id, stage="generate")

    planned = await agent_analyzer.generate_plan_detailed(
        parsed, analysis.understanding, task=row["prompt"]
    )
    progress.plan = planned
    progress.design = (
        planned.design.model_dump(mode="json", by_alias=True)
        if planned.design is not None
        else None
    )
    await _record_plan(
        session,
        task_id=task_id,
        plan=planned,
        design=progress.design,
        forbidden=forbidden,
    )

    return analysis, planned


def _understanding_payload(
    understanding: agent_plan.Understanding, *, spec_id: str
) -> dict[str, Any]:
    """The understanding as the create response carries it.

    The same serializer, so the audit stores what the client was told rather than
    a second rendering that could drift from it.
    """
    return _understanding_response(understanding, spec_id=spec_id).model_dump(
        mode="json", by_alias=True
    )


async def _record_analysis(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    analysis: agent_analyzer.AnalysisOutcome,
    understanding: Mapping[str, Any] | None,
    forbidden: Sequence[str] = (),
) -> None:
    """Who analysed the document, what they understood, what the call cost."""
    await agent_audit.save_analysis(
        session,
        task_id=task_id,
        provider=analysis.provider,
        model=analysis.model,
        prompt=analysis.prompt,
        usage=analysis.usage,
        understanding=understanding,
        forbidden_values=forbidden,
    )


async def _record_plan(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    plan: agent_analyzer.PlanOutcome,
    design: Mapping[str, Any] | None,
    forbidden: Sequence[str] = (),
) -> None:
    """Who designed the plan, what they designed, what the call cost."""
    await agent_audit.save_plan(
        session,
        task_id=task_id,
        provider=plan.provider,
        model=plan.model,
        prompt=plan.prompt,
        usage=plan.usage,
        design=design,
        forbidden_values=forbidden,
    )


async def _forbidden_values(
    session: AsyncSession, row: Mapping[str, Any], variables: Mapping[str, str]
) -> list[str]:
    """Every value a plan must not contain: the request's, and the environment's.

    The environment's values are read here and nowhere else -- not returned to a
    caller, not logged, not stored.  They are compared against the serialised
    plan and dropped.
    """
    values = [value for value in variables.values() if isinstance(value, str)]

    if row["environment_id"] is not None:
        rows = (
            await session.execute(
                text(
                    "SELECT value_encrypted FROM environment_variables "
                    "WHERE environment_id = :environment AND enabled"
                ),
                {"environment": row["environment_id"]},
            )
        ).all()
        values.extend(value for (value,) in rows if isinstance(value, str))

    return values


async def _persist(
    session: AsyncSession, *, row: Mapping[str, Any], plan: Any, task_id: uuid.UUID
) -> None:
    """Write the plan tree -- the only write of the four plan-side tables.

    A single call, and the only one in this module that writes a plan: the
    stage functions returned values and this is where they become rows, with
    `agent_task_id` set to the task that produced them.
    """
    await _create_plan_tree(
        session,
        project_id=row["project_id"],
        spec_id=row["spec_id"],
        plan=plan,
        agent_task_id=task_id,
    )


async def _fail(
    session: AsyncSession,
    task_id: uuid.UUID,
    refusal: PlanPipelineError,
    issues: Sequence[dict[str, str]] | None = None,
    *,
    progress: _Progress | None = None,
) -> None:
    """Roll the write transaction back, then record the refusal on the task.

    The rollback comes first and is not optional: a failed statement leaves the
    transaction aborted, and the status update would raise 25P02 inside it.  What
    the rollback buys is the contract's rule -- a refused plan writes no rows at
    all, not even half a tree.
    """
    await session.rollback()

    if issues:
        logger.warning("agent task %s refused: %s", task_id, issues)
    else:
        logger.warning("agent task %s failed: %s", task_id, refusal.detail)

    # The rollback took the audit's mid-flight notes with it, so what the model
    # produced before the failure is written again from the tracker: a task that
    # fails at validation is exactly when "what did it understand, and what did
    # it design" matters most, and the audit is the only place that can answer it.
    if progress is not None:
        if progress.analysis is not None:
            await _record_analysis(
                session,
                task_id=task_id,
                analysis=progress.analysis,
                understanding=progress.understanding,
                forbidden=progress.forbidden,
            )

        if progress.plan is not None:
            await _record_plan(
                session,
                task_id=task_id,
                plan=progress.plan,
                design=progress.design,
                forbidden=progress.forbidden,
            )

        await agent_audit.fail(
            session,
            task_id=task_id,
            stage=progress.stage,
            code=refusal.code,
            message=refusal.detail,
        )

    await _set_status(session, task_id, _FAILED)
    await session.commit()


async def _set_status(session: AsyncSession, task_id: uuid.UUID, status: str) -> None:
    task = await session.get(AgentTask, task_id)

    if task is None:  # pragma: no cover - the row was just read
        raise _task_not_found(str(task_id))

    task.status = status
    await session.flush()


# --------------------------------------------------------------------------- #
# read
# --------------------------------------------------------------------------- #


async def get_task_audit(session: AsyncSession, *, task_id: str) -> AgentTaskAuditResponse:
    """What the pipeline recorded about one task: who decided what, and what it cost.

    The audit is not the task: a task can fail before a model is ever called, and
    a task created before this record existed has none at all.  An unknown task
    is the same task-not-found the other agent routes answer; a known task with
    no record says so with its own code, rather than pretending the task is gone.
    """
    parsed_id = _task_uuid(task_id)

    if parsed_id is None:
        raise _task_not_found(task_id)

    if await session.get(AgentTask, parsed_id) is None:
        raise _task_not_found(task_id)

    record = await agent_audit.load(session, task_id=parsed_id)

    if record is None:
        raise AppError(
            404,
            code="audit-not-found",
            message_key=_NOT_FOUND,
            details={"taskId": task_id},
        )

    return _audit_response(record)


def _audit_response(record: Mapping[str, Any]) -> AgentTaskAuditResponse:
    """The stored record, as the wire contract spells it."""
    usage = record.get("usage") or {}

    return AgentTaskAuditResponse(
        task_id=record["task_id"],
        status=record["status"],
        failure_stage=record["failure_stage"],
        failure_code=record["failure_code"],
        failure_message=record["failure_message"],
        analyzer=AgentAuditStageResponse(
            provider=record["analyzer_provider"],
            model=record["analyzer_model"],
            prompt_version=record["analyzer_prompt"],
        ),
        planner=AgentAuditStageResponse(
            provider=record["planner_provider"],
            model=record["planner_model"],
            prompt_version=record["planner_prompt"],
        ),
        understanding=record["understanding"],
        plan_design=record["plan_design"],
        usage=AgentUsageResponse(
            analyze=_usage_counts(usage.get("analyze")),
            generate_plan=_usage_counts(usage.get("generatePlan")),
        ),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def _usage_counts(counts: Mapping[str, Any] | None) -> AgentUsageCounts | None:
    """One stage's counts, or nothing when the stage called no model."""
    if not counts:
        return None

    return AgentUsageCounts(
        input_tokens=counts.get("inputTokens"),
        cached_input_tokens=counts.get("cachedInputTokens"),
        output_tokens=counts.get("outputTokens"),
        reasoning_tokens=counts.get("reasoningTokens"),
        total_tokens=counts.get("totalTokens"),
    )


async def get_task(session: AsyncSession, *, task_id: str) -> AgentTaskResponse:
    """A task and its plan, as stored.

    A failed task answers with its status and no failure: agent_tasks has no
    error column, so the reason a task failed is only ever on the response that
    caused it.  That is a recorded gap (contract section 13, G4), not an
    oversight.
    """
    parsed_id = _task_uuid(task_id)
    if parsed_id is None:
        raise _task_not_found(task_id)

    if await _load_task(session, parsed_id) is None:
        raise _task_not_found(task_id)

    return await _response(session, parsed_id)


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #

_TASK_SELECT = """
    SELECT agent_tasks.id AS id,
           agent_tasks.status AS status,
           agent_tasks.prompt AS prompt,
           agent_tasks.spec_id AS spec_id,
           agent_tasks.environment_id AS environment_id,
           agent_tasks.created_at AS created_at,
           agent_tasks.updated_at AS updated_at,
           projects.id AS project_id,
           projects.public_id AS project_public_id,
           environments.public_id AS environment_public_id,
           api_specs.slug AS slug
    FROM agent_tasks
    JOIN projects ON projects.id = agent_tasks.project_id
    JOIN api_specs ON api_specs.id = agent_tasks.spec_id
    LEFT JOIN environments ON environments.id = agent_tasks.environment_id
    WHERE agent_tasks.id = :task
"""


async def _load_task(session: AsyncSession, task_id: uuid.UUID) -> Mapping[str, Any] | None:
    """The task and the three identities a response needs, in one statement."""
    return (
        (await session.execute(text(_TASK_SELECT), {"task": task_id})).mappings().one_or_none()
    )


async def _find_plan(session: AsyncSession, project_id: uuid.UUID, slug: str) -> str | None:
    """The stored plan id for a document's slug, if there is one."""
    return (
        await session.execute(
            text(
                "SELECT public_id FROM test_plans "
                "WHERE project_id = :project AND public_id = :public_id"
            ),
            {"project": project_id, "public_id": f"plan_{slug}"},
        )
    ).scalar_one_or_none()


_PLAN_ROW = """
    SELECT test_plans.id AS id,
           test_plans.public_id AS public_id,
           test_plans.name AS name,
           test_plans.description AS goal,
           test_plans.status AS status,
           test_plans.risk_level AS risk_level,
           test_plans.source AS source,
           test_plans.created_at AS created_at,
           test_plans.approved_at AS approved_at,
           test_plans.rejected_at AS rejected_at,
           test_plans.rejection_reason AS rejection_reason
    FROM test_plans
    WHERE test_plans.agent_task_id = :task
"""

_PLAN_SCENARIOS = """
    SELECT test_scenarios.id AS id,
           test_scenarios.scenario_key AS scenario_key,
           test_scenarios.name AS name,
           test_scenarios.description AS description,
           test_scenarios.expected AS expected,
           test_scenarios.risk_level AS risk_level,
           test_scenarios.sort_order AS sort_order
    FROM test_scenarios
    WHERE test_scenarios.plan_id = :plan
    ORDER BY test_scenarios.sort_order, test_scenarios.scenario_key
"""

_PLAN_STEPS = """
    SELECT test_steps.scenario_id AS scenario_id,
           test_steps.step_key AS step_key,
           test_steps.description AS description,
           test_steps.step_type AS step_type,
           test_steps.sort_order AS sort_order,
           test_steps.produces AS produces,
           test_steps.consumes AS consumes,
           test_steps.config AS config
    FROM test_steps
    JOIN test_scenarios ON test_scenarios.id = test_steps.scenario_id
    WHERE test_scenarios.plan_id = :plan
    ORDER BY test_scenarios.sort_order, test_steps.sort_order, test_steps.step_key
"""

_PLAN_ASSERTIONS = """
    SELECT test_assertions.scenario_id AS scenario_id,
           test_assertions.assertion_key AS assertion_key,
           test_assertions.assertion_type AS assertion_type,
           test_assertions.target AS target,
           test_assertions.expected_value AS expected_value,
           test_assertions.description AS description
    FROM test_assertions
    JOIN test_scenarios ON test_scenarios.id = test_assertions.scenario_id
    WHERE test_scenarios.plan_id = :plan
    ORDER BY test_scenarios.sort_order, test_assertions.assertion_key
"""


def _config_value(config: Any, key: str) -> str | None:
    """One string out of a step's `config` blob, or nothing.

    `config` is JSONB, so a value that is not a string is treated as absent
    rather than handed to a response model that would reject it.  Same rule the
    run snapshot applies when it reads the pair back (Phase 8.2 Step 1).
    """
    if not isinstance(config, dict):
        return None

    value = config.get(key)

    return value if isinstance(value, str) and value != "" else None


async def _plan_tree(
    session: AsyncSession, *, task_id: uuid.UUID, project_id: str, spec_id: str
) -> AgentPlanResponse | None:
    """The plan a task wrote, read back as the tree the console reviews.

    Four statements whatever the plan holds -- the row, its scenarios, their
    steps and their assertions -- because the alternative is one query per row
    and a plan is not small.  `test_plans.agent_task_id` is the link: the
    relationship the schema reserved is finally the one the read path uses.
    """
    plan = (await session.execute(text(_PLAN_ROW), {"task": task_id})).mappings().one_or_none()

    if plan is None:
        return None

    scenarios = (await session.execute(text(_PLAN_SCENARIOS), {"plan": plan["id"]})).mappings().all()
    steps = (await session.execute(text(_PLAN_STEPS), {"plan": plan["id"]})).mappings().all()
    assertions = (
        await session.execute(text(_PLAN_ASSERTIONS), {"plan": plan["id"]})
    ).mappings().all()

    steps_by_scenario: dict[Any, list[AgentStepResponse]] = {}
    for row in steps:
        steps_by_scenario.setdefault(row["scenario_id"], []).append(
            AgentStepResponse(
                id=row["step_key"],
                index=row["sort_order"],
                kind=row["step_type"],
                description=row["description"],
                # The plan's endpoint id is the frontend's own string and has no
                # column: the FK points at api_endpoints, which are never
                # materialised.  Null is the honest answer, not a placeholder.
                endpoint_id=None,
                method=_config_value(row["config"], "method"),
                path=_config_value(row["config"], "path"),
                produces=row["produces"],
                consumes=list(row["consumes"] or []),
            )
        )

    assertions_by_scenario: dict[Any, list[AgentAssertionResponse]] = {}
    for row in assertions:
        assertions_by_scenario.setdefault(row["scenario_id"], []).append(
            AgentAssertionResponse(
                id=row["assertion_key"],
                kind=row["assertion_type"],
                target=row["target"],
                # The column is JSONB; the wire field is the string the plan
                # carried, which is what create-run reads back too.
                expected=row["expected_value"] if isinstance(row["expected_value"], str) else "",
                description=row["description"],
            )
        )

    return AgentPlanResponse(
        id=plan["public_id"],
        project_id=project_id,
        spec_id=spec_id,
        name=plan["name"],
        goal=plan["goal"],
        risk_level=plan["risk_level"],
        status=plan["status"],
        scenarios=[
            AgentScenarioResponse(
                id=row["scenario_key"],
                index=row["sort_order"],
                name=row["name"],
                description=row["description"],
                risk_level=row["risk_level"],
                steps=steps_by_scenario.get(row["id"], []),
                expected=row["expected"],
                assertions=assertions_by_scenario.get(row["id"], []),
            )
            for row in scenarios
        ],
        source=plan["source"],
        generated_at=plan["created_at"],
        approved_at=plan["approved_at"],
        rejected_at=plan["rejected_at"],
        rejection_reason=plan["rejection_reason"],
    )


def _understanding_response(
    understanding: agent_plan.Understanding, *, spec_id: str
) -> AgentUnderstandingResponse:
    """The understanding as the wire shape the console's types already describe.

    Mapped field by field rather than dumped: the dataclasses are the pipeline's
    internal shape and the response is a contract, and the two are allowed to
    differ without the frontend noticing only if something does the mapping.
    """
    authentication = understanding.authentication

    return AgentUnderstandingResponse(
        spec_id=spec_id,
        endpoints=[
            AgentEndpointResponse(
                id=endpoint.id,
                method=endpoint.method,
                path=endpoint.path,
                resource_id=endpoint.resource_id,
                summary=endpoint.summary,
                requires_auth=endpoint.requires_auth,
                path_params=list(endpoint.path_params),
                required_body_props=list(endpoint.required_body_props),
                constrained_body_props=list(endpoint.constrained_body_props),
                response_statuses=list(endpoint.response_statuses),
                response_props=list(endpoint.response_props),
            )
            for endpoint in understanding.endpoints
        ],
        resources=[
            AgentResourceResponse(
                id=resource.id, name=resource.name, endpoint_ids=list(resource.endpoint_ids)
            )
            for resource in understanding.resources
        ],
        authentication=AgentAuthenticationResponse(
            scheme=authentication.scheme,
            scheme_name=authentication.scheme_name,
            header_name=authentication.header_name,
            token_source_endpoint_id=authentication.token_source_endpoint_id,
            token_field=authentication.token_field,
            protected_endpoint_count=authentication.protected_endpoint_count,
        ),
        dependencies=[
            AgentDependencyResponse(
                id=dependency.id,
                from_endpoint_id=dependency.from_endpoint_id,
                to_endpoint_id=dependency.to_endpoint_id,
                kind=dependency.kind,
                binding=dependency.binding,
                rationale=dependency.rationale,
            )
            for dependency in understanding.dependencies
        ],
        risks=[
            AgentRiskResponse(
                id=risk.id,
                level=risk.level,
                category=risk.category,
                title=risk.title,
                detail=risk.detail,
                related_endpoint_ids=list(risk.related_endpoint_ids),
                fields=list(risk.fields),
            )
            for risk in understanding.risks
        ],
        findings=[
            AgentFindingResponse(
                id=finding.id,
                action=finding.action,
                decision_summary=finding.decision_summary,
                result=finding.result,
                evidence=[
                    AgentEvidenceResponse(label=item["label"], value=item["value"])
                    for item in finding.evidence
                ],
                at=finding.at,
            )
            for finding in understanding.findings
        ],
        analyzed_at=understanding.analyzed_at,
    )


async def _response(
    session: AsyncSession,
    task_id: uuid.UUID,
    *,
    understanding: AgentUnderstandingResponse | None = None,
) -> AgentTaskResponse:
    """The task, its stored plan, and -- only right after a run -- the understanding."""
    row = await _load_task(session, task_id)
    if row is None:  # pragma: no cover - callers only pass live ids
        raise _task_not_found(str(task_id))

    spec_id = spec_id_for(row["slug"])

    return AgentTaskResponse(
        id=str(row["id"]),
        project_id=row["project_public_id"],
        spec_id=spec_id,
        environment_id=row["environment_public_id"],
        prompt=row["prompt"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        plan=await _plan_tree(
            session,
            task_id=task_id,
            project_id=row["project_public_id"],
            spec_id=spec_id,
        ),
        understanding=understanding,
    )
