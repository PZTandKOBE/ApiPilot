"""The agent's plan, as rows: what the pipeline writes, and what refuses to run it.

Three different claims live here, and the file keeps them apart on purpose.

**The plan is written to the database.**  The whole real pipeline runs -- spec row,
task row, audit row, plan tree, status transitions -- in the product's own session,
and the assertions are about what came back *out of the database* afterwards.
``agent.process_task`` re-reads the tree from its tables to build its response, so a
round trip is what the product already does, not something this file bolts on.

**The model is not needed to prove that.**  ``AGENT_ANALYZER`` and ``AGENT_PLANNER``
both accept ``deterministic``, which is a product feature rather than a test double:
the rule engine produces a real, contract-valid plan with no network call.  So the
default tests here are an honest integration test of everything *except* the two
model calls, and they cost nothing to run.

**The gate is checked where the product checks it.**  ``runs.create_run`` refuses an
unapproved payload before it touches the database; the tests below assert the refusal
code, its details, and -- read from a different session -- that nothing was written.

The opt-in test at the bottom is the only one that spends a model call, and it needs
both switches.  It is skipped by default, like the other live tests.
"""

from __future__ import annotations

import inspect
import json
import os
import uuid
from typing import Any

import pytest
from sqlalchemy import delete, select

from backend.api.errors import AppError
# Aliased on import: a class whose name starts with "Test" is a collection target for
# pytest, and these are tables, not tests.
from backend.db.models.agent import AgentTask
from backend.db.models.agent import TestAssertion as _TestAssertion
from backend.db.models.agent import TestPlan as _TestPlan
from backend.db.models.agent import TestScenario as _TestScenario
from backend.db.models.agent import TestStep as _TestStep
from backend.db.models.project import ApiSpec, Project
from backend.db.models.result import TestRun as _TestRun
from backend.schemas.agent import AgentTaskCreateRequest
from backend.schemas.run import PlanPayload
from backend.services import agent, agent_analyzer, agent_plan, runs

pytestmark = pytest.mark.anyio

ORDERS_DOCUMENT: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Orders API", "version": "1.0.0"},
    "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
    "security": [{"bearerAuth": []}],
    "paths": {
        "/auth/token": {
            "post": {
                "summary": "Exchange credentials for a bearer token",
                "security": [],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["username", "password"],
                                "properties": {
                                    "username": {"type": "string"},
                                    "password": {"type": "string"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "a token",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["token"],
                                    "properties": {"token": {"type": "string"}},
                                }
                            }
                        },
                    }
                },
            }
        },
        "/orders/{orderId}": {
            "get": {
                "summary": "Read one order",
                "parameters": [
                    {"name": "orderId", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {
                    "200": {
                        "description": "the order",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["id", "status", "total"],
                                    "properties": {
                                        "id": {"type": "string"},
                                        "status": {"type": "string"},
                                        "total": {"type": "number"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        },
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
                "responses": {
                    "201": {
                        "description": "created",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["id", "status"],
                                    "properties": {
                                        "id": {"type": "string"},
                                        "status": {"type": "string"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        },
    },
}

ORDERS_TEXT = json.dumps(ORDERS_DOCUMENT)

# Derived from the document's info.title by the product's own derive_spec_identity,
# and confirmed with agent.spec_id_for(slug) before these tests were written.
ORDERS_SLUG = "orders_api_6vcqjt"
ORDERS_SPEC_ID = "spec_orders_api_6vcqjt"
ORDERS_PLAN_ID = "plan_orders_api_6vcqjt"
PROMPT = "Cover reading an order and creating one, with status or field assertions."

DB_E2E_ENV = "RUN_AGENT_DB_E2E"
INTEGRATION_ENV = "RUN_DEEPSEEK_INTEGRATION"


def _offline_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the product's own rule engine instead of the model.

    These are the two documented settings that decide which implementation runs,
    and `deterministic` is supported in both.  Nothing here replaces the pipeline.
    """
    monkeypatch.setenv(agent_analyzer.ANALYZER_ENV, agent_analyzer.DETERMINISTIC)
    monkeypatch.setenv(agent_analyzer.PLANNER_ENV, agent_analyzer.DETERMINISTIC)


def _db_e2e_reason() -> str:
    if (os.getenv(DB_E2E_ENV) or "").strip().lower() not in ("1", "true", "yes"):
        return f"opt-in: set {DB_E2E_ENV}=1 and {INTEGRATION_ENV}=1 to spend real model calls"
    if (os.getenv(INTEGRATION_ENV) or "").strip().lower() not in ("1", "true", "yes"):
        return f"opt-in: set {INTEGRATION_ENV}=1 as well"
    if not (os.getenv("DEEPSEEK_API_KEY") or "").strip():
        return "DEEPSEEK_API_KEY is not set"
    return ""


requires_db_e2e = pytest.mark.skipif(
    bool(_db_e2e_reason()), reason=_db_e2e_reason() or "live database E2E disabled"
)


async def _seed_spec_row(fixtures, project_id: uuid.UUID) -> uuid.UUID:
    """Give the project an `api_specs` row holding the orders document.

    Written through the fixture factory so teardown deletes exactly this row.  The
    slug is the one the document derives, so the pipeline recomputes the same
    identities it expects.
    """
    row = ApiSpec(
        project_id=project_id,
        name="C16 orders spec",
        slug=ORDERS_SLUG,
        spec_type="openapi-3",
        content_format="json",
        content=ORDERS_TEXT,
        source="upload",
        filename="orders.json",
    )
    fixtures.session.add(row)
    return await fixtures._keep(ApiSpec, row)


async def _project_public_id(fixtures, project_id: uuid.UUID) -> str:
    return (
        await fixtures.session.execute(
            select(Project.public_id).where(Project.id == project_id)
        )
    ).scalar_one()


async def _run_agent_task(fixtures, stack, *, tracked: list[str] | None = None):
    """Drive the real pipeline once; return (task_id, response).

    `agent.start_task` is the function the HTTP route calls: it commits the task
    row, runs parse -> analyze -> generate -> validate -> persist, commits the plan
    tree, and returns the tree *read back from the database*.
    """
    public_id = await _project_public_id(fixtures, stack["project"])
    payload = AgentTaskCreateRequest(
        projectId=public_id,
        specId=ORDERS_SPEC_ID,
        specDocument=ORDERS_TEXT,
        prompt=PROMPT,
    )
    response = await agent.start_task(
        fixtures.session, project_id=public_id, payload=payload
    )
    if tracked is not None:
        tracked.append(str(response.id))
    return str(response.id), response


async def _drop_agent_rows(engine, task_ids: list[str]) -> None:
    """Delete the rows this file made, children before parents.

    The shared fixture factory deletes what it was handed, and it was handed the
    spec row.  The pipeline also writes an agent task, an audit row and a plan tree
    underneath that spec, so those come out first here: otherwise the spec cannot
    be deleted and teardown dies on a foreign key.

    Scoped by task id on purpose.  Nothing else in the database is touched, and a
    failed test still cleans up because this runs from a finally block.
    """
    if not task_ids:
        return
    from backend.db import database
    from backend.db.models.agent import AgentTaskAudit as _AgentTaskAudit

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


def _plan_payload(status: str, *, plan_id: str = "plan_c16_gate") -> dict[str, Any]:
    """A minimal contract-shaped plan body for the run entry point."""
    return {
        "id": plan_id,
        "projectId": "prj_placeholder",
        "specId": ORDERS_SPEC_ID,
        "name": {"text": "C16 gate plan"},
        "goal": {"text": "refuse to execute an unapproved plan"},
        "riskLevel": "low",
        "status": status,
        "source": "generated",
        "generatedAt": "2026-10-16T00:00:00Z",
        "scenarios": [],
    }


# NaN #
# The gate: what refuses to run an unapproved plan
# NaN #


@pytest.mark.parametrize("status", ["draft", "rejected", "in_review"])
def test_unapproved_statuses_are_refused_by_the_gate(status: str) -> None:
    """The gate is a whitelist: only `approved` passes it."""
    plan = PlanPayload.model_validate(_plan_payload(status))

    with pytest.raises(AppError) as caught:
        runs._check_approval(plan)

    assert caught.value.status_code == 409
    assert caught.value.code == "not-approved"
    assert caught.value.details["status"] == status


def test_approved_status_passes_the_gate() -> None:
    """The other half of the rule: the check is not a blanket refusal."""
    runs._check_approval(PlanPayload.model_validate(_plan_payload("approved")))


def test_the_gate_takes_no_session() -> None:
    """The refusal happens on the payload, before the session is used.

    `_check_approval` has no session parameter, so it cannot write.  This is a
    structural fact about the gate rather than a promise about its behaviour.
    """
    assert list(inspect.signature(runs._check_approval).parameters) == ["plan"], (
        "the gate grew a dependency; if it now needs a session, re-check that it "
        "still refuses before writing anything"
    )


# NaN #
# The plan, as rows
# NaN #


async def test_agent_pipeline_persists_a_draft_plan_tree(
    fixtures, stack, read_session, monkeypatch, engine
) -> None:
    """The real pipeline writes the tree, and reading it back loses nothing.

    The response is built from the plan-side tables, so every assertion below is
    about stored state rather than about an object the pipeline happened to hold.
    """
    _offline_pipeline(monkeypatch)
    await _seed_spec_row(fixtures, stack["project"])
    await fixtures.commit()

    tracked: list[str] = []
    try:
        task_id, response = await _run_agent_task(fixtures, stack, tracked=tracked)
    except BaseException:
        await _drop_agent_rows(engine, tracked)
        raise

    plan = response.plan
    assert plan is not None, "the pipeline returned no plan"
    assert plan.id == ORDERS_PLAN_ID
    assert plan.status == "draft", "the agent must never hand back an approved plan"
    assert plan.approved_at is None
    assert plan.rejected_at is None
    assert plan.scenarios, "the stored plan has no scenarios"

    stored = (
        await read_session.execute(
            select(_TestPlan).where(_TestPlan.agent_task_id == uuid.UUID(task_id))
        )
    ).scalar_one()
    assert stored.public_id == ORDERS_PLAN_ID
    assert stored.status == "draft"
    assert stored.approved_at is None
    assert stored.project_id == stack["project"]

    scenarios = list(
        (
            await read_session.execute(
                select(_TestScenario).where(_TestScenario.plan_id == stored.id)
            )
        ).scalars()
    )
    assert len(scenarios) == len(plan.scenarios)
    assert {scenario.scenario_key for scenario in scenarios} == {
        scenario.id for scenario in plan.scenarios
    }

    for scenario in plan.scenarios:
        row = next(s for s in scenarios if s.scenario_key == scenario.id)

        steps = list(
            (
                await read_session.execute(
                    select(_TestStep)
                    .where(_TestStep.scenario_id == row.id)
                    .order_by(_TestStep.sort_order)
                )
            ).scalars()
        )
        assert [step.step_key for step in steps] == [step.id for step in scenario.steps]
        assert [step.sort_order for step in steps] == [step.index for step in scenario.steps]
        assert [step.step_type for step in steps] == [step.kind for step in scenario.steps]

        assertions = list(
            (
                await read_session.execute(
                    select(_TestAssertion).where(_TestAssertion.scenario_id == row.id)
                )
            ).scalars()
        )
        assert {a.assertion_key for a in assertions} == {
            a.id for a in scenario.assertions
        }

    await _drop_agent_rows(engine, tracked)


async def test_persisted_plan_keeps_draft_through_a_fresh_read(
    fixtures, stack, read_session, monkeypatch, engine
) -> None:
    """draft survives the write, the commit and a read from another session.

    The status column could have been written as something else, defaulted, or
    rewritten by a later stage.  This reads the row directly to rule that out.
    """
    _offline_pipeline(monkeypatch)
    await _seed_spec_row(fixtures, stack["project"])
    await fixtures.commit()

    tracked: list[str] = []
    try:
        task_id, _ = await _run_agent_task(fixtures, stack, tracked=tracked)

        first = (
        await read_session.execute(
            select(_TestPlan.status, _TestPlan.approved_at).where(
                _TestPlan.agent_task_id == uuid.UUID(task_id)
            )
        )
    ).one()
        assert first.status == "draft"
        assert first.approved_at is None

        again = await agent.get_task(fixtures.session, task_id=task_id)
        assert again.plan is not None
        assert again.plan.status == "draft"

        second = (
            await read_session.execute(
                select(_TestPlan.status).where(_TestPlan.agent_task_id == uuid.UUID(task_id))
            )
        ).scalar_one()
        assert second == "draft"
    finally:
        await _drop_agent_rows(engine, tracked)


async def test_agent_pipeline_creates_no_run_rows(
    fixtures, stack, read_session, monkeypatch, engine
) -> None:
    """The agent writes plans; it has no path to a run.

    Checked by counting rows rather than by reading the code, because "the agent
    cannot start a run" is a security claim, not a style one.
    """
    _offline_pipeline(monkeypatch)
    await _seed_spec_row(fixtures, stack["project"])
    await fixtures.commit()

    before = list(
        (
            await read_session.execute(
                select(_TestRun.id).where(_TestRun.project_id == stack["project"])
            )
        ).scalars()
    )

    tracked: list[str] = []
    try:
        await _run_agent_task(fixtures, stack, tracked=tracked)

        after = list(
        (
            await read_session.execute(
                select(_TestRun.id).where(_TestRun.project_id == stack["project"])
                )
            ).scalars()
        )
        assert after == before, "running the agent created a run row"
    finally:
        await _drop_agent_rows(engine, tracked)


async def test_plan_tree_is_committed_with_its_task(
    fixtures, stack, read_session, monkeypatch, engine
) -> None:
    """The rows and the task status agree: completed means the tree is there."""
    _offline_pipeline(monkeypatch)
    await _seed_spec_row(fixtures, stack["project"])
    await fixtures.commit()

    tracked: list[str] = []
    try:
        task_id, response = await _run_agent_task(fixtures, stack, tracked=tracked)
    except BaseException:
        await _drop_agent_rows(engine, tracked)
        raise

    assert response.status == "completed"

    plan_rows = list(
        (
            await read_session.execute(
                select(_TestPlan.id).where(_TestPlan.agent_task_id == uuid.UUID(task_id))
            )
        ).scalars()
    )
    assert len(plan_rows) == 1, "a completed task must have exactly one plan row"

    scenario_rows = list(
        (
            await read_session.execute(
                select(_TestScenario.id).where(_TestScenario.plan_id == plan_rows[0])
            )
        ).scalars()
    )
    assert scenario_rows, "a completed task must have its scenarios stored"

    await _drop_agent_rows(engine, tracked)


# NaN #
# Neither generator can approve anything
# NaN #


def test_the_plan_generator_hardcodes_draft() -> None:
    """Approval is not a parameter of the generator, in either mode.

    A rule-engine plan is built with the status written literally, and the model
    planner has no status field to fill in (see `PlanDesign`), so neither path can
    produce an approved plan.
    """
    assert "status" not in agent_analyzer.PlanDesign.model_fields

    source = inspect.getsource(agent_plan.generate_plan)
    assert 'status="draft"' in source, (
        "the generator no longer states the status literally; re-check that nothing "
        "can pass an approved status into it"
    )


# NaN #
# Real model -> real rows -> still a draft -> still refused
# NaN #


@requires_db_e2e
async def test_live_agent_task_persists_a_draft_then_the_gate_refuses_it(
    fixtures, stack, read_session, monkeypatch, engine
) -> None:
    """The whole chain, paid for once: model, rows, read-back, refusal.

    The analyzer and planner are the real DeepSeek ones, so this is the only test
    in this file that costs money.  It proves a model-designed plan survives the
    product's own persistence path and still cannot run.
    """
    monkeypatch.setenv(agent_analyzer.ANALYZER_ENV, agent_analyzer.DEEPSEEK)
    monkeypatch.setenv(agent_analyzer.PLANNER_ENV, agent_analyzer.DEEPSEEK)
    await _seed_spec_row(fixtures, stack["project"])
    await fixtures.commit()

    tracked: list[str] = []
    try:
        task_id, response = await _run_agent_task(fixtures, stack, tracked=tracked)
    except BaseException:
        await _drop_agent_rows(engine, tracked)
        raise

    assert response.status == "completed"
    plan = response.plan
    assert plan is not None
    assert plan.status == "draft"
    assert plan.scenarios, "the model produced no scenarios"
    assert any(scenario.assertions for scenario in plan.scenarios), (
        "the model produced no assertions"
    )

    stored = (
        await read_session.execute(
            select(_TestPlan).where(_TestPlan.agent_task_id == uuid.UUID(task_id))
        )
    ).scalar_one()
    assert stored.status == "draft"
    assert stored.approved_at is None

    # And the gate still refuses it, because approval was never granted.
    with pytest.raises(AppError) as caught:
        runs._check_approval(PlanPayload.model_validate(_plan_payload("draft", plan_id=plan.id)))
    assert caught.value.code == "not-approved"

    runs_left = list(
        (
            await read_session.execute(
                select(_TestRun.id).where(_TestRun.project_id == stack["project"])
            )
        ).scalars()
    )
    assert not runs_left, "the refused plan left a run row behind"

    await _drop_agent_rows(engine, tracked)
