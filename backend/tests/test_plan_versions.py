"""Plan regeneration and versioning, against the real pipeline and database.

The product's own deterministic planner is used (both stages set to
`deterministic`), so these are integration tests of the task lifecycle,
version allocation and plan persistence without a model call.  Every assertion
about plans is read back from `test_plans` / `test_scenarios` / `test_steps`,
not from the object the service happened to return.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from sqlalchemy import delete, select

from backend.api.errors import AppError
from backend.db import database
from backend.db.models.agent import AgentTask
from backend.db.models.agent import AgentTaskAudit as _AgentTaskAudit
from backend.db.models.agent import TestAssertion as _TestAssertion
from backend.db.models.agent import TestPlan as _TestPlan
from backend.db.models.agent import TestScenario as _TestScenario
from backend.db.models.agent import TestStep as _TestStep
from backend.db.models.project import ApiSpec, Project
from backend.db.models.result import TestRun as _TestRun
from backend.schemas.agent import AgentTaskCreateRequest
from backend.services import agent, agent_analyzer
from backend.services.agent import derive_spec_identity, probe_document
from backend.services.agent_plan import PlanPipelineError

pytestmark = pytest.mark.anyio

ORDERS_DOCUMENT: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "C31 Orders API", "version": "1.0.0"},
    "paths": {
        "/orders": {
            "post": {
                "summary": "Create an order",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["sku", "quantity"],
                                "properties": {
                                    "sku": {"type": "string"},
                                    "quantity": {"type": "integer"},
                                },
                            }
                        }
                    },
                },
                "responses": {"201": {"description": "created"}},
            }
        },
        "/orders/{orderId}": {
            "get": {
                "summary": "Read one order",
                "responses": {"200": {"description": "the order"}},
            }
        },
    },
}

ORDERS_TEXT = json.dumps(ORDERS_DOCUMENT)
ORDERS_IDENTITY = derive_spec_identity(
    spec_document=ORDERS_TEXT, spec_id="spec_probe", facts=probe_document(ORDERS_TEXT)
)
ORDERS_SLUG = ORDERS_IDENTITY.slug
ORDERS_SPEC_ID = "spec_" + ORDERS_SLUG
ORDERS_PLAN_ID = "plan_" + ORDERS_SLUG
PROMPT = "Cover creating and reading an order."


def _offline_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(agent_analyzer.ANALYZER_ENV, agent_analyzer.DETERMINISTIC)
    monkeypatch.setenv(agent_analyzer.PLANNER_ENV, agent_analyzer.DETERMINISTIC)


async def _project_public_id(fixtures, project_id: uuid.UUID) -> str:
    return (
        await fixtures.session.execute(
            select(Project.public_id).where(Project.id == project_id)
        )
    ).scalar_one()


async def _run_task(fixtures, stack, *, regenerate: bool = False):
    public_id = await _project_public_id(fixtures, stack["project"])
    payload = AgentTaskCreateRequest(
        projectId=public_id,
        specId=ORDERS_SPEC_ID,
        specDocument=ORDERS_TEXT,
        prompt=PROMPT,
        regenerate=regenerate,
    )
    return await agent.start_task(
        fixtures.session, project_id=public_id, payload=payload
    )


async def _create_task(fixtures, stack, *, regenerate: bool = False) -> uuid.UUID:
    public_id = await _project_public_id(fixtures, stack["project"])
    payload = AgentTaskCreateRequest(
        projectId=public_id,
        specId=ORDERS_SPEC_ID,
        specDocument=ORDERS_TEXT,
        prompt=PROMPT,
        regenerate=regenerate,
    )
    return await agent.create_task(
        fixtures.session, project_id=public_id, payload=payload
    )


async def _list_plans(fixtures, stack) -> list[Any]:
    public_id = await _project_public_id(fixtures, stack["project"])
    return await agent.list_plans(fixtures.session, project_id=public_id)


async def _orders_plans(fixtures, stack) -> list[Any]:
    return [
        plan
        for plan in await _list_plans(fixtures, stack)
        if plan.spec_id == ORDERS_SPEC_ID
    ]


async def _plan_ids(fixtures, stack) -> dict[str, Any]:
    return {plan.id: plan for plan in await _orders_plans(fixtures, stack)}


async def _drop_agent_rows(engine, task_ids: list[str]) -> None:
    if not task_ids:
        return

    keys = [uuid.UUID(value) for value in task_ids]
    async with database.AsyncSessionLocal() as session:
        plan_ids = list(
            (
                await session.execute(
                    select(_TestPlan.id).where(_TestPlan.agent_task_id.in_(keys))
                )
            ).scalars()
        )
        if plan_ids:
            await session.execute(
                delete(_TestRun).where(_TestRun.plan_id.in_(plan_ids))
            )
            scenario_ids = list(
                (
                    await session.execute(
                        select(_TestScenario.id).where(_TestScenario.plan_id.in_(plan_ids))
                    )
                ).scalars()
            )
            if scenario_ids:
                for table in (_TestAssertion, _TestStep):
                    await session.execute(
                        delete(table).where(table.scenario_id.in_(scenario_ids))
                    )
                await session.execute(
                    delete(_TestScenario).where(_TestScenario.id.in_(scenario_ids))
                )
            await session.execute(delete(_TestPlan).where(_TestPlan.id.in_(plan_ids)))
        await session.execute(
            delete(_AgentTaskAudit).where(_AgentTaskAudit.task_id.in_(keys))
        )
        await session.execute(delete(AgentTask).where(AgentTask.id.in_(keys)))
        await session.commit()


async def _tree_row_ids(
    fixtures, plan_public_id: str
) -> tuple[set[uuid.UUID], set[uuid.UUID], set[uuid.UUID]]:
    plan_id = (
        await fixtures.session.execute(
            select(_TestPlan.id).where(_TestPlan.public_id == plan_public_id)
        )
    ).scalar_one()
    scenario_ids = set(
        (
            await fixtures.session.execute(
                select(_TestScenario.id).where(_TestScenario.plan_id == plan_id)
            )
        ).scalars()
    )
    step_ids = set(
        (
            await fixtures.session.execute(
                select(_TestStep.id).where(_TestStep.scenario_id.in_(scenario_ids))
            )
        ).scalars()
    )
    assertion_ids = set(
        (
            await fixtures.session.execute(
                select(_TestAssertion.id).where(
                    _TestAssertion.scenario_id.in_(scenario_ids)
                )
            )
        ).scalars()
    )
    return scenario_ids, step_ids, assertion_ids


async def _spec_id(fixtures, plan_id: uuid.UUID) -> uuid.UUID:
    return (
        await fixtures.session.execute(
            select(_TestPlan.spec_id).where(_TestPlan.id == plan_id)
        )
    ).scalar_one()


def test_run_plan_payload_accepts_the_version_metadata() -> None:
    from backend.schemas.run import PlanPayload

    parsed = PlanPayload.model_validate(
        {
            "id": "plan_c31_payload",
            "projectId": "prj_c31",
            "specId": "spec_c31",
            "version": 2,
            "isCurrent": True,
            "runCount": 3,
            "name": {"text": "C31 plan"},
            "goal": {"text": "version metadata"},
            "riskLevel": "low",
            "status": "approved",
            "scenarios": [],
            "source": "generated",
            "generatedAt": "2026-10-17T00:00:00Z",
        }
    )

    assert parsed.version == 2
    assert parsed.is_current is True
    assert parsed.run_count == 3


def test_the_plan_version_collection_route_is_registered() -> None:
    from backend.app import create_app

    paths = create_app().openapi()["paths"]
    assert "/api/projects/{project_id}/plans" in paths


# --------------------------------------------------------------------------- #
# Version allocation
# --------------------------------------------------------------------------- #


async def test_first_generation_is_version_one_with_the_legacy_id(
    fixtures, stack, monkeypatch, engine
) -> None:
    _offline_pipeline(monkeypatch)
    tracked: list[str] = []

    try:
        response = await _run_task(fixtures, stack)
        tracked.append(str(response.id))

        assert response.plan is not None
        assert response.plan.id == ORDERS_PLAN_ID
        assert response.plan.version == 1
        assert response.plan.is_current is True
        assert response.plan.run_count == 0
        assert response.plan.status == "draft"

        plans = await _orders_plans(fixtures, stack)
        assert [plan.id for plan in plans] == [ORDERS_PLAN_ID]
        assert plans[0].version == 1
    finally:
        await _drop_agent_rows(engine, tracked)


async def test_ordinary_second_generation_still_returns_plan_exists(
    fixtures, stack, monkeypatch, engine
) -> None:
    _offline_pipeline(monkeypatch)
    tracked: list[str] = []

    try:
        response = await _run_task(fixtures, stack)
        tracked.append(str(response.id))

        with pytest.raises(AppError) as caught:
            await _run_task(fixtures, stack)

        assert caught.value.status_code == 409
        assert caught.value.code == "plan-exists"
        assert caught.value.details == {"planId": ORDERS_PLAN_ID}
        assert len(await _orders_plans(fixtures, stack)) == 1
    finally:
        await _drop_agent_rows(engine, tracked)


async def test_regenerate_creates_v2_without_overwriting_v1(
    fixtures, stack, monkeypatch, engine
) -> None:
    _offline_pipeline(monkeypatch)
    tracked: list[str] = []

    try:
        first = await _run_task(fixtures, stack)
        tracked.append(str(first.id))
        assert first.plan is not None
        before = {
            "id": first.plan.id,
            "scenarios": [scenario.id for scenario in first.plan.scenarios],
            "steps": [
                step.id for scenario in first.plan.scenarios for step in scenario.steps
            ],
            "assertions": [
                assertion.id
                for scenario in first.plan.scenarios
                for assertion in scenario.assertions
            ],
        }

        second = await _run_task(fixtures, stack, regenerate=True)
        tracked.append(str(second.id))

        assert second.plan is not None
        assert second.plan.id == ORDERS_PLAN_ID + "_v2"
        assert second.plan.version == 2
        assert second.plan.is_current is True
        assert second.plan.id != first.plan.id

        plans = await _plan_ids(fixtures, stack)
        assert set(plans) == {ORDERS_PLAN_ID, ORDERS_PLAN_ID + "_v2"}
        assert plans[ORDERS_PLAN_ID].version == 1
        assert plans[ORDERS_PLAN_ID].is_current is False
        assert plans[ORDERS_PLAN_ID + "_v2"].version == 2
        assert plans[ORDERS_PLAN_ID + "_v2"].is_current is True

        old = plans[ORDERS_PLAN_ID]
        assert [scenario.id for scenario in old.scenarios] == before["scenarios"]
        assert [
            step.id for scenario in old.scenarios for step in scenario.steps
        ] == before["steps"]
        assert [
            assertion.id
            for scenario in old.scenarios
            for assertion in scenario.assertions
        ] == before["assertions"]
    finally:
        await _drop_agent_rows(engine, tracked)


async def test_consecutive_regenerations_create_independent_versions(
    fixtures, stack, monkeypatch, engine
) -> None:
    _offline_pipeline(monkeypatch)
    tracked: list[str] = []

    try:
        first = await _run_task(fixtures, stack)
        tracked.append(str(first.id))
        second = await _run_task(fixtures, stack, regenerate=True)
        tracked.append(str(second.id))
        third = await _run_task(fixtures, stack, regenerate=True)
        tracked.append(str(third.id))

        assert second.plan is not None and third.plan is not None
        assert [second.plan.version, third.plan.version] == [2, 3]
        assert [second.plan.id, third.plan.id] == [
            ORDERS_PLAN_ID + "_v2",
            ORDERS_PLAN_ID + "_v3",
        ]

        plans = await _plan_ids(fixtures, stack)
        assert set(plans) == {
            ORDERS_PLAN_ID,
            ORDERS_PLAN_ID + "_v2",
            ORDERS_PLAN_ID + "_v3",
        }
        current = [plan.id for plan in plans.values() if plan.is_current]
        assert current == [ORDERS_PLAN_ID + "_v3"]

        # Each version has its own scenario / step / assertion rows, not a
        # shared tree.  The keys repeat across versions by design; the row ids
        # must not.
        all_scenarios: set[uuid.UUID] = set()
        all_steps: set[uuid.UUID] = set()
        all_assertions: set[uuid.UUID] = set()
        expected_scenarios = 0
        for plan in plans.values():
            scenarios, steps, assertions = await _tree_row_ids(fixtures, plan.id)
            assert scenarios and steps and assertions
            assert not (scenarios & all_scenarios)
            assert not (steps & all_steps)
            assert not (assertions & all_assertions)
            all_scenarios |= scenarios
            all_steps |= steps
            all_assertions |= assertions
            expected_scenarios += len(plan.scenarios)
        assert len(all_scenarios) == expected_scenarios
    finally:
        await _drop_agent_rows(engine, tracked)


async def test_new_version_starts_draft_and_old_approval_is_untouched(
    fixtures, stack, monkeypatch, engine
) -> None:
    _offline_pipeline(monkeypatch)
    tracked: list[str] = []

    try:
        first = await _run_task(fixtures, stack)
        tracked.append(str(first.id))
        old_row = (
            await fixtures.session.execute(
                select(_TestPlan).where(_TestPlan.public_id == ORDERS_PLAN_ID)
            )
        ).scalar_one()
        old_row.status = "approved"
        await fixtures.session.commit()

        second = await _run_task(fixtures, stack, regenerate=True)
        tracked.append(str(second.id))

        assert second.plan is not None
        assert second.plan.status == "draft"
        assert second.plan.approved_at is None

        plans = await _plan_ids(fixtures, stack)
        assert plans[ORDERS_PLAN_ID].status == "approved"
        assert plans[ORDERS_PLAN_ID + "_v2"].status == "draft"
    finally:
        await _drop_agent_rows(engine, tracked)


async def test_regenerate_failure_leaves_the_old_plan_intact(
    fixtures, stack, monkeypatch, engine
) -> None:
    _offline_pipeline(monkeypatch)
    tracked: list[str] = []

    try:
        first = await _run_task(fixtures, stack)
        tracked.append(str(first.id))
        before = await _orders_plans(fixtures, stack)

        task_id = await _create_task(fixtures, stack, regenerate=True)
        tracked.append(str(task_id))

        async def refuse(*args, **kwargs):
            raise PlanPipelineError("generate-failed", "forced failure")

        monkeypatch.setattr(agent_analyzer, "generate_plan_detailed", refuse)

        with pytest.raises(AppError):
            await agent.process_task(
                fixtures.session, task_id=task_id, regenerate=True
            )

        after = await _orders_plans(fixtures, stack)
        assert [plan.id for plan in after] == [plan.id for plan in before]
        assert after[0].scenarios == before[0].scenarios
    finally:
        await _drop_agent_rows(engine, tracked)


async def test_existing_run_keeps_its_plan_id_across_regeneration(
    fixtures, stack, monkeypatch, engine
) -> None:
    _offline_pipeline(monkeypatch)
    tracked: list[str] = []

    try:
        first = await _run_task(fixtures, stack)
        tracked.append(str(first.id))

        old_plan = (
            await fixtures.session.execute(
                select(_TestPlan).where(_TestPlan.public_id == ORDERS_PLAN_ID)
            )
        ).scalar_one()
        run = _TestRun(
            project_id=stack["project"],
            plan_id=old_plan.id,
            spec_id=old_plan.spec_id,
            environment_id=None,
            plan_name={"text": "C31 historical run"},
            base_url="http://127.0.0.1:9",
            status="passed",
        )
        fixtures.session.add(run)
        await fixtures.session.flush()
        run_id = run.id
        await fixtures.session.commit()

        second = await _run_task(fixtures, stack, regenerate=True)
        tracked.append(str(second.id))

        stored = (
            await fixtures.session.execute(
                select(_TestRun).where(_TestRun.id == run_id)
            )
        ).scalar_one()
        assert stored.plan_id == old_plan.id
        assert stored.plan_name["text"] == "C31 historical run"

        plans = await _plan_ids(fixtures, stack)
        assert plans[ORDERS_PLAN_ID].run_count == 1
        assert plans[ORDERS_PLAN_ID + "_v2"].run_count == 0
    finally:
        await _drop_agent_rows(engine, tracked)


async def test_versions_are_independent_between_documents_in_one_project(
    fixtures, stack, monkeypatch, engine
) -> None:
    _offline_pipeline(monkeypatch)
    tracked: list[str] = []

    payments_document = {
        "openapi": "3.0.3",
        "info": {"title": "C31 Payments API", "version": "1.0.0"},
        "paths": {
            "/payments": {
                "post": {
                    "summary": "Create a payment",
                    "responses": {"201": {"description": "created"}},
                }
            }
        },
    }
    payments_text = json.dumps(payments_document)
    payments_identity = derive_spec_identity(
        spec_document=payments_text,
        spec_id="spec_probe",
        facts=probe_document(payments_text),
    )
    payments_spec_id = "spec_" + payments_identity.slug

    try:
        orders = await _run_task(fixtures, stack)
        tracked.append(str(orders.id))

        public_id = await _project_public_id(fixtures, stack["project"])
        payments_payload = AgentTaskCreateRequest(
            projectId=public_id,
            specId=payments_spec_id,
            specDocument=payments_text,
            prompt="Cover payment creation.",
        )
        payments = await agent.start_task(
            fixtures.session, project_id=public_id, payload=payments_payload
        )
        tracked.append(str(payments.id))

        assert orders.plan is not None and payments.plan is not None
        assert orders.plan.id != payments.plan.id
        assert orders.plan.version == 1
        assert payments.plan.version == 1
        assert orders.plan.id == ORDERS_PLAN_ID
        assert payments.plan.id == "plan_" + payments_identity.slug

        plans = await _list_plans(fixtures, stack)
        orders_series = [plan for plan in plans if plan.spec_id == ORDERS_SPEC_ID]
        payments_series = [plan for plan in plans if plan.spec_id == payments_spec_id]
        assert [plan.id for plan in orders_series] == [ORDERS_PLAN_ID]
        assert [plan.id for plan in payments_series] == [payments.plan.id]
    finally:
        await _drop_agent_rows(engine, tracked)


async def test_versions_are_independent_between_projects(
    fixtures, stack, monkeypatch, engine
) -> None:
    _offline_pipeline(monkeypatch)
    tracked: list[str] = []

    try:
        first = await _run_task(fixtures, stack)
        tracked.append(str(first.id))

        guest = await fixtures.guest()
        other_project = await fixtures.project(guest)
        await fixtures.commit()
        other_public = await _project_public_id(fixtures, other_project)
        payload = AgentTaskCreateRequest(
            projectId=other_public,
            specId=ORDERS_SPEC_ID,
            specDocument=ORDERS_TEXT,
            prompt=PROMPT,
        )
        response = await agent.start_task(
            fixtures.session, project_id=other_public, payload=payload
        )
        tracked.append(str(response.id))

        assert response.plan is not None
        assert response.plan.id == ORDERS_PLAN_ID
        assert response.plan.version == 1
        assert response.plan.is_current is True

        project_one_plans = await _orders_plans(fixtures, stack)
        assert [plan.id for plan in project_one_plans] == [ORDERS_PLAN_ID]
        other_plans = await agent.list_plans(
            fixtures.session, project_id=other_public
        )
        assert [plan.id for plan in other_plans if plan.spec_id == ORDERS_SPEC_ID] == [
            ORDERS_PLAN_ID
        ]
    finally:
        await _drop_agent_rows(engine, tracked)


async def test_concurrent_regenerations_allocate_distinct_versions(
    fixtures, stack, monkeypatch, engine
) -> None:
    _offline_pipeline(monkeypatch)
    tracked: list[str] = []

    try:
        first = await _run_task(fixtures, stack)
        tracked.append(str(first.id))

        public_id = await _project_public_id(fixtures, stack["project"])

        def payload() -> AgentTaskCreateRequest:
            return AgentTaskCreateRequest(
                projectId=public_id,
                specId=ORDERS_SPEC_ID,
                specDocument=ORDERS_TEXT,
                prompt=PROMPT,
                regenerate=True,
            )

        async with database.AsyncSessionLocal() as one, database.AsyncSessionLocal() as two:
            responses = await asyncio.gather(
                agent.start_task(one, project_id=public_id, payload=payload()),
                agent.start_task(two, project_id=public_id, payload=payload()),
            )

        for response in responses:
            tracked.append(str(response.id))

        versions = sorted(response.plan.version for response in responses if response.plan)
        ids = sorted(response.plan.id for response in responses if response.plan)
        assert versions == [2, 3]
        assert ids == [ORDERS_PLAN_ID + "_v2", ORDERS_PLAN_ID + "_v3"]

        async with database.AsyncSessionLocal() as session:
            plans = await agent.list_plans(session, project_id=public_id)
        series = [plan for plan in plans if plan.spec_id == ORDERS_SPEC_ID]
        assert sorted(plan.version for plan in series) == [1, 2, 3]
        assert [plan.id for plan in series if plan.is_current] == [
            ORDERS_PLAN_ID + "_v3"
        ]
    finally:
        await _drop_agent_rows(engine, tracked)
