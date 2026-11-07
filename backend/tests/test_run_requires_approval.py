"""Run creation is gated by the stored approval receipt, not by the request body.

The old contract let a client say plan.status = approved. These tests pin the
replacement: the run endpoint looks the plan up in this project, reads the row
status and the content fingerprint, and executes the stored plan. A body that
claims approval proves nothing; a body that differs from the stored plan is
not what runs.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select, update

from backend.api.errors import AppError
from backend.db.models.agent import TestPlan, TestScenario, TestStep
from backend.db.models.project import Environment, Project
from backend.db.models.result import RunAssertion, RunScenario, RunStep, TestRun
from backend.db.models.user import GuestSession
from backend.schemas.run import PlanPayload, RunCreateRequest
from backend.services import agent, run_executor, runs

from tests.plan_support import approve_plan_row, persist_approved_plan, persist_plan
from tests.test_run_execution import (
    ASSERTION_KEY,
    ASSERT_STEP,
    CREATE_STEP,
    EXTRACT_STEP,
    PLAN_ID,
    READ_STEP,
    SCENARIO_KEY,
    _plan_payload,
    _project_public_id,
    _run_body,
    _seed_environment,
)

pytestmark = pytest.mark.anyio


async def _prepare(fixtures, stack, *, approve: bool = True):
    await _seed_environment(fixtures, stack["project"])
    await fixtures.commit()
    public_id = await _project_public_id(fixtures, stack["project"])
    body = _run_body(public_id)
    payload = RunCreateRequest.model_validate(body)

    if approve:
        await persist_approved_plan(
            fixtures.session,
            project_id=stack["project"],
            payload=payload,
            project_public_id=public_id,
        )
    else:
        await persist_plan(
            fixtures.session, project_id=stack["project"], payload=payload
        )

    await fixtures.commit()
    return public_id, payload


async def _create(fixtures, monkeypatch, *, public_id: str, payload: RunCreateRequest):
    async def _do_not_schedule(run_id):
        return None

    monkeypatch.setattr(run_executor, "schedule_run", _do_not_schedule)
    return await runs.create_run(
        fixtures.session, project_id=public_id, payload=payload
    )


async def _runs_for(session, project_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(TestRun).where(
                TestRun.project_id == project_id
            )
        )
    )


async def test_an_approved_stored_plan_runs_even_when_the_body_says_draft(
    fixtures, stack, monkeypatch
) -> None:
    """The row is the authority; the body status is ignored."""
    public_id, _ = await _prepare(fixtures, stack, approve=True)

    body = _run_body(public_id, status="draft")
    payload = RunCreateRequest.model_validate(body)

    response = await _create(fixtures, monkeypatch, public_id=public_id, payload=payload)

    assert response.status == "queued"
    assert await _runs_for(fixtures.session, stack["project"]) == 1


async def test_a_body_claim_is_not_an_approval(fixtures, stack, monkeypatch) -> None:
    """A draft stored row refuses a body that claims approved, and writes nothing."""
    public_id, _ = await _prepare(fixtures, stack, approve=False)

    body = _run_body(public_id, status="approved")
    payload = RunCreateRequest.model_validate(body)

    with pytest.raises(AppError) as caught:
        await _create(fixtures, monkeypatch, public_id=public_id, payload=payload)

    assert caught.value.status_code == 409
    assert caught.value.code == "not-approved"
    assert await _runs_for(fixtures.session, stack["project"]) == 0

    stored = (
        await fixtures.session.execute(
            select(TestPlan).where(
                TestPlan.project_id == stack["project"],
                TestPlan.public_id == PLAN_ID,
            )
        )
    ).scalar_one()
    assert stored.status == "draft"
    assert stored.approved_at is None
    assert stored.content_hash is None


async def test_content_changed_after_approval_is_refused(
    fixtures, stack, monkeypatch
) -> None:
    """A plan edited after its receipt no longer matches, so the run is refused."""
    public_id, payload = await _prepare(fixtures, stack, approve=True)

    stored = (
        await fixtures.session.execute(
            select(TestPlan).where(
                TestPlan.project_id == stack["project"],
                TestPlan.public_id == PLAN_ID,
            )
        )
    ).scalar_one()
    step = (
        await fixtures.session.execute(
            select(TestStep)
            .join(TestScenario, TestScenario.id == TestStep.scenario_id)
            .where(
                TestScenario.plan_id == stored.id,
                TestStep.step_key == CREATE_STEP,
            )
        )
    ).scalar_one()
    config = dict(step.config or {})
    config["path"] = "/orders/changed"
    await fixtures.session.execute(
        update(TestStep).where(TestStep.id == step.id).values(config=config)
    )
    await fixtures.session.commit()

    with pytest.raises(AppError) as caught:
        await _create(fixtures, monkeypatch, public_id=public_id, payload=payload)

    assert caught.value.status_code == 409
    assert caught.value.code == "plan-changed"
    assert await _runs_for(fixtures.session, stack["project"]) == 0


async def test_an_unstored_plan_is_refused_without_writing_anything(
    fixtures, stack, monkeypatch
) -> None:
    """No auto-materialisation from the body exists any more."""
    await _seed_environment(fixtures, stack["project"])
    await fixtures.commit()
    public_id = await _project_public_id(fixtures, stack["project"])
    payload = RunCreateRequest.model_validate(_run_body(public_id))

    with pytest.raises(AppError) as caught:
        await _create(fixtures, monkeypatch, public_id=public_id, payload=payload)

    assert caught.value.status_code == 404
    assert caught.value.code == "plan-not-found"
    assert await _runs_for(fixtures.session, stack["project"]) == 0
    assert (
        await fixtures.session.scalar(
            select(func.count()).select_from(TestPlan).where(
                TestPlan.project_id == stack["project"],
                TestPlan.public_id == PLAN_ID,
            )
        )
    ) == 0


async def test_a_rejected_plan_is_refused(fixtures, stack, monkeypatch) -> None:
    public_id, payload = await _prepare(fixtures, stack, approve=True)

    project = await fixtures.session.get(Project, stack["project"])
    guest = await fixtures.session.get(GuestSession, stack["guest"])
    assert project is not None and guest is not None
    await agent.reject_plan(
        fixtures.session,
        project=project,
        plan_id=PLAN_ID,
        guest=guest,
        reason="not good enough",
    )
    await fixtures.session.commit()

    with pytest.raises(AppError) as caught:
        await _create(fixtures, monkeypatch, public_id=public_id, payload=payload)

    assert caught.value.code == "not-approved"
    assert caught.value.details["status"] == "rejected"


async def test_a_plan_from_another_project_is_not_found(
    fixtures, stack, monkeypatch
) -> None:
    """Plan ids are project-scoped; the same id elsewhere is not this project."""
    await _seed_environment(fixtures, stack["project"])
    other_project = await fixtures.project(stack["guest"])
    await fixtures.commit()

    public_id = await _project_public_id(fixtures, stack["project"])
    other_public_id = await _project_public_id(fixtures, other_project)

    other_payload = RunCreateRequest.model_validate(_run_body(other_public_id))
    await persist_approved_plan(
        fixtures.session,
        project_id=other_project,
        payload=other_payload,
        project_public_id=other_public_id,
    )
    await fixtures.commit()

    own_payload = RunCreateRequest.model_validate(_run_body(public_id))
    with pytest.raises(AppError) as caught:
        await _create(fixtures, monkeypatch, public_id=public_id, payload=own_payload)

    assert caught.value.status_code == 404
    assert caught.value.code == "plan-not-found"


async def test_tampered_body_content_is_not_what_runs(
    fixtures, stack, monkeypatch
) -> None:
    """The snapshot comes from the stored plan, not from the submitted tree."""
    public_id, payload = await _prepare(fixtures, stack, approve=True)

    tampered = payload.model_copy(deep=True)
    tampered.plan.scenarios[0].steps[0].path = "/tampered"
    tampered.plan.scenarios[0].assertions[0].expected = "999"

    response = await _create(
        fixtures, monkeypatch, public_id=public_id, payload=tampered
    )
    run_id = uuid.UUID(str(response.id))

    scenario = (
        await fixtures.session.execute(
            select(TestScenario)
            .join(TestPlan, TestPlan.id == TestScenario.plan_id)
            .where(TestPlan.public_id == PLAN_ID)
        )
    ).scalars().all()
    stored_scenario = scenario[0]
    stored_step = (
        await fixtures.session.execute(
            select(TestStep).where(
                TestStep.scenario_id == stored_scenario.id,
                TestStep.step_key == CREATE_STEP,
            )
        )
    ).scalar_one()

    # Simpler read: the run snapshot for this run, by key.
    from backend.db.models.result import RunScenario

    run_scenario = (
        await fixtures.session.execute(
            select(RunScenario).where(RunScenario.run_id == run_id)
        )
    ).scalar_one()
    snapshot_step = (
        await fixtures.session.execute(
            select(RunStep).where(
                RunStep.run_scenario_id == run_scenario.id,
                RunStep.step_key == CREATE_STEP,
            )
        )
    ).scalar_one()
    assert snapshot_step.path == (stored_step.config or {}).get("path"), (
        "the run must snapshot the stored plan path, not the tampered body"
    )
    assert snapshot_step.path != "/tampered"


# --------------------------------------------------------------------------- #
# Structural defense: an approved plan can still be an empty tree
# --------------------------------------------------------------------------- #


async def _persist_abnormally_approved(fixtures, stack, mutate):
    await _seed_environment(fixtures, stack["project"])
    await fixtures.commit()
    public_id = await _project_public_id(fixtures, stack["project"])

    plan = _plan_payload()
    plan["id"] = "plan_empty_tree_" + uuid.uuid4().hex[:8]
    mutate(plan)
    body = _run_body(public_id, plan=plan)
    body["planId"] = plan["id"]
    payload = RunCreateRequest.model_validate(body)

    row = await persist_plan(
        fixtures.session, project_id=stack["project"], payload=payload
    )
    project = await fixtures.session.get(Project, stack["project"])
    assert project is not None
    await approve_plan_row(
        fixtures.session,
        project_id=stack["project"],
        row=row,
        project_public_id=public_id,
    )
    await fixtures.commit()
    return public_id, payload


def _issue_rules(error: AppError) -> list[str]:
    details = error.details or {}
    issues = details.get("issues", []) if isinstance(details, dict) else []
    return [issue.get("rule", "") for issue in issues]


async def _assert_create_refused(fixtures, monkeypatch, stack, public_id, payload):
    with pytest.raises(AppError) as caught:
        await _create(fixtures, monkeypatch, public_id=public_id, payload=payload)

    assert caught.value.status_code == 409
    assert caught.value.code == "plan-invalid"
    assert await _runs_for(fixtures.session, stack["project"]) == 0
    project_scenarios = await fixtures.session.scalar(
        select(func.count())
        .select_from(RunScenario)
        .join(TestRun, TestRun.id == RunScenario.run_id)
        .where(TestRun.project_id == stack["project"])
    )
    project_steps = await fixtures.session.scalar(
        select(func.count())
        .select_from(RunStep)
        .join(RunScenario, RunScenario.id == RunStep.run_scenario_id)
        .join(TestRun, TestRun.id == RunScenario.run_id)
        .where(TestRun.project_id == stack["project"])
    )
    project_assertions = await fixtures.session.scalar(
        select(func.count())
        .select_from(RunAssertion)
        .join(RunScenario, RunScenario.id == RunAssertion.run_scenario_id)
        .join(TestRun, TestRun.id == RunScenario.run_id)
        .where(TestRun.project_id == stack["project"])
    )
    assert project_scenarios == 0
    assert project_steps == 0
    assert project_assertions == 0
    return caught.value


async def test_an_approved_empty_plan_cannot_create_a_run(
    fixtures, stack, monkeypatch
) -> None:
    def mutate(plan):
        plan["scenarios"] = []

    public_id, payload = await _persist_abnormally_approved(fixtures, stack, mutate)
    await _assert_create_refused(fixtures, monkeypatch, stack, public_id, payload)


async def test_an_approved_plan_with_an_empty_scenario_cannot_create_a_run(
    fixtures, stack, monkeypatch
) -> None:
    def mutate(plan):
        plan["scenarios"][0]["steps"] = []
        plan["scenarios"][0]["assertions"] = []

    public_id, payload = await _persist_abnormally_approved(fixtures, stack, mutate)
    await _assert_create_refused(fixtures, monkeypatch, stack, public_id, payload)


async def test_an_approved_assert_only_plan_cannot_create_a_run(
    fixtures, stack, monkeypatch
) -> None:
    def mutate(plan):
        plan["scenarios"][0]["steps"] = [
            {
                "id": ASSERT_STEP,
                "index": 0,
                "kind": "assert",
                "description": {"text": "assert"},
                "endpointId": None,
                "method": None,
                "path": None,
                "produces": None,
                "consumes": [],
            }
        ]
        plan["scenarios"][0]["assertions"] = []

    public_id, payload = await _persist_abnormally_approved(fixtures, stack, mutate)
    await _assert_create_refused(fixtures, monkeypatch, stack, public_id, payload)


async def test_a_missing_materialized_step_is_refused(
    fixtures, stack, monkeypatch
) -> None:
    public_id, payload = await _prepare(fixtures, stack, approve=True)
    original = runs._load_plan_tree

    async def missing_step(session, plan_id):
        materialization = await original(session, plan_id)
        materialization.step_ids.pop((SCENARIO_KEY, CREATE_STEP), None)
        return materialization

    monkeypatch.setattr(runs, "_load_plan_tree", missing_step)
    await _assert_create_refused(fixtures, monkeypatch, stack, public_id, payload)


async def test_a_missing_source_step_mapping_is_refused(
    fixtures, stack, monkeypatch
) -> None:
    public_id, _ = await _prepare(fixtures, stack, approve=True)

    # A valid source-bearing plan, then remove the target from the materialized
    # map.  This is the defensive DB layer the product cannot receive from a
    # normal client payload.
    plan = _plan_payload()
    plan["id"] = "plan_source_missing_" + uuid.uuid4().hex[:8]
    plan["scenarios"][0]["steps"][1]["sourcePath"] = "$.id"
    plan["scenarios"][0]["steps"][1]["sourceStepId"] = READ_STEP
    body = _run_body(public_id, plan=plan)
    body["planId"] = plan["id"]
    payload = RunCreateRequest.model_validate(body)
    row = await persist_plan(
        fixtures.session, project_id=stack["project"], payload=payload
    )
    project = await fixtures.session.get(Project, stack["project"])
    await approve_plan_row(
        fixtures.session,
        project_id=stack["project"],
        row=row,
        project_public_id=public_id,
    )
    await fixtures.commit()

    original = runs._load_plan_tree

    async def missing_source(session, plan_id):
        materialization = await original(session, plan_id)
        materialization.step_ids.pop((SCENARIO_KEY, READ_STEP), None)
        return materialization

    monkeypatch.setattr(runs, "_load_plan_tree", missing_source)
    error = await _assert_create_refused(
        fixtures, monkeypatch, stack, public_id, payload
    )
    # The ordinary step check sees the missing step first; the source check is
    # still present in the same issue list.  Isolation of the source branch is
    # covered by the helper-level test below.
    assert set(_issue_rules(error)) == {"step-materialization", "source-materialization"}


async def test_missing_source_materialization_is_reported_in_isolation() -> None:
    """The source branch alone, with every payload step otherwise materialized.

    A source target that passes plan_structure is necessarily a payload step, so
    the ordinary step loop and the source check read the same step_ids key.  It
    is therefore impossible to remove only the source lookup from a create_run
    that still passes the structure gate.  This minimal payload exercises the
    defensive branch directly: the target is absent from the payload (so the step
    loop is clean) while the extract still names it.
    """
    data = _plan_payload()
    steps = data["scenarios"][0]["steps"]
    extract = next(step for step in steps if step["id"] == EXTRACT_STEP)
    extract["sourcePath"] = "$.orderId"
    extract["sourceStepId"] = READ_STEP
    data["scenarios"][0]["steps"] = [
        step for step in steps if step["id"] != READ_STEP
    ]
    plan = PlanPayload.model_validate(data)

    materialization = runs._PlanMaterialization(uuid.uuid4())
    materialization.scenario_ids[SCENARIO_KEY] = uuid.uuid4()
    materialization.step_ids = {
        (SCENARIO_KEY, step.id): uuid.uuid4()
        for step in plan.scenarios[0].steps
    }
    materialization.assertion_ids[(SCENARIO_KEY, ASSERTION_KEY)] = uuid.uuid4()

    issues = runs._materialization_issues(plan, materialization)
    assert [issue["rule"] for issue in issues] == ["source-materialization"]


async def test_a_valid_source_bearing_plan_creates_a_v1_run(
    fixtures, stack, monkeypatch
) -> None:
    public_id, _ = await _prepare(fixtures, stack, approve=False)
    plan = _plan_payload()
    plan["id"] = "plan_source_valid_" + uuid.uuid4().hex[:8]
    plan["scenarios"][0]["steps"][1]["sourcePath"] = "$.id"
    plan["scenarios"][0]["steps"][1]["sourceStepId"] = READ_STEP
    body = _run_body(public_id, plan=plan)
    body["planId"] = plan["id"]
    payload = RunCreateRequest.model_validate(body)
    row = await persist_plan(
        fixtures.session, project_id=stack["project"], payload=payload
    )
    project = await fixtures.session.get(Project, stack["project"])
    await approve_plan_row(
        fixtures.session,
        project_id=stack["project"],
        row=row,
        project_public_id=public_id,
    )
    await fixtures.commit()

    response = await _create(fixtures, monkeypatch, public_id=public_id, payload=payload)
    stored = await fixtures.session.get(TestRun, uuid.UUID(str(response.id)))
    assert stored is not None
    assert stored.snapshot_version == 1


async def test_a_legacy_path_only_extract_can_create_a_v1_run(
    fixtures, stack, monkeypatch
) -> None:
    public_id, _ = await _prepare(fixtures, stack, approve=False)
    plan = _plan_payload()
    plan["id"] = "plan_legacy_source_" + uuid.uuid4().hex[:8]
    plan["scenarios"][0]["steps"][1]["sourcePath"] = "$.id"
    body = _run_body(public_id, plan=plan)
    body["planId"] = plan["id"]
    payload = RunCreateRequest.model_validate(body)
    row = await persist_plan(
        fixtures.session, project_id=stack["project"], payload=payload
    )
    project = await fixtures.session.get(Project, stack["project"])
    await approve_plan_row(
        fixtures.session,
        project_id=stack["project"],
        row=row,
        project_public_id=public_id,
    )
    await fixtures.commit()

    response = await _create(fixtures, monkeypatch, public_id=public_id, payload=payload)
    stored = await fixtures.session.get(TestRun, uuid.UUID(str(response.id)))
    assert stored is not None
    assert stored.snapshot_version == 1


async def test_a_missing_scenario_materialization_is_refused(
    fixtures, stack, monkeypatch
) -> None:
    public_id, payload = await _prepare(fixtures, stack, approve=True)
    original = runs._load_plan_tree

    async def missing_scenario(session, plan_id):
        materialization = await original(session, plan_id)
        materialization.scenario_ids.pop(SCENARIO_KEY, None)
        return materialization

    monkeypatch.setattr(runs, "_load_plan_tree", missing_scenario)
    error = await _assert_create_refused(
        fixtures, monkeypatch, stack, public_id, payload
    )
    assert _issue_rules(error) == ["scenario-materialization"]


async def test_a_missing_assertion_materialization_is_refused(
    fixtures, stack, monkeypatch
) -> None:
    public_id, payload = await _prepare(fixtures, stack, approve=True)
    original = runs._load_plan_tree

    async def missing_assertion(session, plan_id):
        materialization = await original(session, plan_id)
        materialization.assertion_ids.pop((SCENARIO_KEY, ASSERTION_KEY), None)
        return materialization

    monkeypatch.setattr(runs, "_load_plan_tree", missing_assertion)
    error = await _assert_create_refused(
        fixtures, monkeypatch, stack, public_id, payload
    )
    assert _issue_rules(error) == ["assertion-materialization"]
