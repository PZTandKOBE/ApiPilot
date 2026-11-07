"""A run executes its own snapshot, never the plan it came from.

These tests mutate or delete the plan after the run exists and then execute the
run: the HTTP calls and the Extract results must still be the ones captured at
creation.  They also prove the executor issues no SQL against plan tables, and
that a historical run without a complete snapshot is refused instead of being
silently executed with current plan content.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, event, func, literal_column, select, text, update

from backend.api.errors import AppError
from backend.db.models.agent import TestPlan, TestScenario, TestStep
from backend.db.models.result import RunScenario, RunStep
from backend.db.models.result import TestRun as _TestRun
from backend.db.database import AsyncSessionLocal
from backend.schemas.run import RunCreateRequest
from backend.services import plan_hash, run_executor, runs

from tests.plan_support import persist_approved_plan
from tests.test_run_execution import (
    CREATE_STEP,
    EXTRACT_STEP,
    PLAN_ID,
    READ_STEP,
    _create_run,
    _install_client,
    _plan_payload,
    _project_public_id,
    _run_body,
    _seed_environment,
)

pytestmark = pytest.mark.anyio

_PLAN_TABLES = ("test_steps", "test_plans", "test_scenarios", "test_assertions")


async def _plan_row(fixtures, project_id: uuid.UUID) -> TestPlan:
    return (
        await fixtures.session.execute(
            select(TestPlan).where(
                TestPlan.project_id == project_id, TestPlan.public_id == PLAN_ID
            )
        )
    ).scalar_one()


async def _step_by_key(fixtures, plan: TestPlan, key: str) -> TestStep:
    return (
        await fixtures.session.execute(
            select(TestStep)
            .join(TestScenario, TestScenario.id == TestStep.scenario_id)
            .where(TestScenario.plan_id == plan.id, TestStep.step_key == key)
        )
    ).scalar_one()


async def _run_steps(fixtures, run_id: uuid.UUID) -> dict[str, RunStep]:
    rows = (
        await fixtures.session.execute(
            select(RunStep)
            .join(RunScenario, RunScenario.id == RunStep.run_scenario_id)
            .where(RunScenario.run_id == run_id)
        )
    ).scalars().all()
    return {row.step_key: row for row in rows}


def _with_body_and_source() -> dict[str, Any]:
    plan = copy.deepcopy(_plan_payload())
    steps = plan["scenarios"][0]["steps"]
    steps[0]["body"] = {"name": "snapshot"}
    steps[0]["bodyPresent"] = True
    steps[1]["sourcePath"] = "$.orderId"
    steps[1]["sourceStepId"] = READ_STEP
    return plan


async def test_a_new_run_carries_every_execution_field(fixtures, stack, monkeypatch) -> None:
    plan = _with_body_and_source()
    run_id = await _create_run(fixtures, stack, monkeypatch, plan=plan)

    stored = (await fixtures.session.execute(
        select(_TestRun).where(_TestRun.id == run_id)
    )).scalar_one()
    assert stored.snapshot_version == 1

    steps = await _run_steps(fixtures, run_id)
    read = steps[READ_STEP]
    extract = steps[EXTRACT_STEP]

    assert (read.step_type, read.method, read.path) == ("request", "GET", "/orders/order_1")
    assert read.body_present is True
    assert read.body == {"name": "snapshot"}
    assert read.produces is None
    assert extract.step_type == "extract"
    assert extract.produces == "orderId"
    assert extract.source_path == "$.orderId"
    assert extract.source_step_key == READ_STEP


async def test_editing_the_plan_after_creation_does_not_change_the_run(
    fixtures, stack, monkeypatch
) -> None:
    plan = _with_body_and_source()
    run_id = await _create_run(fixtures, stack, monkeypatch, plan=plan)
    project = stack["project"]

    plan_row = await _plan_row(fixtures, project)
    read = await _step_by_key(fixtures, plan_row, READ_STEP)
    extract = await _step_by_key(fixtures, plan_row, EXTRACT_STEP)
    await fixtures.session.execute(
        update(TestStep)
        .where(TestStep.id == read.id)
        .values(config={"method": "PATCH", "path": "/tampered", "body": {"evil": True}, "bodyPresent": True})
    )
    await fixtures.session.execute(
        update(TestStep)
        .where(TestStep.id == extract.id)
        .values(produces="tamperedVar")
    )
    await fixtures.session.commit()

    client = _install_client(monkeypatch)
    await run_executor.execute_run(run_id)

    assert [(request.method, request.url.path) for request in client.sent] == [
        ("GET", "/orders/order_1"),
        ("POST", "/orders"),
    ]
    assert client.sent[1].url.params["for"] == "order_1"
    assert client.sent[0].content == b'{"name":"snapshot"}', (
        "the body the plan had at creation was replaced by the edited one"
    )

    run = (await fixtures.session.execute(
        select(_TestRun).where(_TestRun.id == run_id)
    )).scalar_one()
    assert run.status == "passed"


async def test_deleting_plan_children_after_creation_does_not_change_the_run(
    fixtures, stack, monkeypatch
) -> None:
    plan = _with_body_and_source()
    run_id = await _create_run(fixtures, stack, monkeypatch, plan=plan)
    project = stack["project"]

    plan_row = await _plan_row(fixtures, project)
    # CASCADE removes test_steps/test_assertions; run_steps.source_* become
    # NULL through SET NULL, which is exactly the audit-only link the executor
    # must not need.
    await fixtures.session.execute(
        delete(TestScenario).where(TestScenario.plan_id == plan_row.id)
    )
    await fixtures.session.commit()

    steps = await _run_steps(fixtures, run_id)
    assert steps[READ_STEP].source_step_id is None
    assert steps[EXTRACT_STEP].source_step_id is None

    client = _install_client(monkeypatch)
    await run_executor.execute_run(run_id)

    assert [(request.method, request.url.path) for request in client.sent] == [
        ("GET", "/orders/order_1"),
        ("POST", "/orders"),
    ]
    run = (await fixtures.session.execute(
        select(_TestRun).where(_TestRun.id == run_id)
    )).scalar_one()
    assert run.status == "passed"


async def test_soft_deleting_the_plan_after_creation_does_not_change_the_run(
    fixtures, stack, monkeypatch
) -> None:
    run_id = await _create_run(fixtures, stack, monkeypatch)
    plan_row = await _plan_row(fixtures, stack["project"])
    plan_row.deleted_at = datetime.now(timezone.utc)
    await fixtures.session.commit()

    client = _install_client(monkeypatch)
    await run_executor.execute_run(run_id)

    assert len(client.sent) == 2
    run = (await fixtures.session.execute(
        select(_TestRun).where(_TestRun.id == run_id)
    )).scalar_one()
    assert run.status == "passed"


async def test_execution_issues_no_sql_against_plan_tables(
    fixtures, stack, monkeypatch, engine
) -> None:
    run_id = await _create_run(fixtures, stack, monkeypatch)
    _install_client(monkeypatch)

    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement.lower())

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        await run_executor.execute_run(run_id)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)

    offenders = [
        statement
        for statement in statements
        if any(table in statement for table in _PLAN_TABLES)
    ]
    assert offenders == [], offenders


async def test_a_legacy_run_is_refused_before_any_http_request(
    fixtures, stack, monkeypatch
) -> None:
    run_id = await _create_run(fixtures, stack, monkeypatch)
    await fixtures.session.execute(
        update(_TestRun).where(_TestRun.id == run_id).values(snapshot_version=0)
    )
    await fixtures.session.commit()

    client = _install_client(monkeypatch)
    await run_executor.execute_run(run_id)

    assert client.sent == []
    run = (await fixtures.session.execute(
        select(_TestRun).where(_TestRun.id == run_id)
    )).scalar_one()
    assert run.status == "failed"
    assert run.error_code == run_executor.SNAPSHOT_UNAVAILABLE
    assert "create a new run" in (run.error_message or "")


async def test_body_semantics_are_preserved_on_the_snapshot(
    fixtures, stack, monkeypatch
) -> None:
    """SQL NULL, JSON null, {} and [] must not collapse into each other."""
    plan = copy.deepcopy(_plan_payload())
    scenario = plan["scenarios"][0]
    scenario["steps"] = [
        {"id": "step_no_body", "index": 0, "kind": "request", "description": {"text": "none"},
         "endpointId": None, "method": "GET", "path": "/none", "produces": None, "consumes": []},
        {"id": "step_json_null", "index": 1, "kind": "request", "description": {"text": "null"},
         "endpointId": None, "method": "POST", "path": "/null", "produces": None, "consumes": [],
         "body": None, "bodyPresent": True},
        {"id": "step_empty_object", "index": 2, "kind": "request", "description": {"text": "object"},
         "endpointId": None, "method": "POST", "path": "/object", "produces": None, "consumes": [],
         "body": {}, "bodyPresent": True},
        {"id": "step_empty_array", "index": 3, "kind": "request", "description": {"text": "array"},
         "endpointId": None, "method": "POST", "path": "/array", "produces": None, "consumes": [],
         "body": [], "bodyPresent": True},
    ]
    scenario["assertions"] = [
        {"id": "assertion_noop", "kind": "status", "target": "status", "expected": "200",
         "description": {"text": "noop"}, "stepId": None}
    ]
    run_id = await _create_run(fixtures, stack, monkeypatch, plan=plan)

    rows = (await fixtures.session.execute(
        select(
            RunStep.step_key,
            RunStep.body_present,
            RunStep.body,
            literal_column("run_steps.body IS NULL").label("body_sql_null"),
        )
        .join(RunScenario, RunScenario.id == RunStep.run_scenario_id)
        .where(RunScenario.run_id == run_id)
    )).all()
    by_key = {row.step_key: row for row in rows}

    assert by_key["step_no_body"].body_present is False
    assert by_key["step_no_body"].body_sql_null is True

    assert by_key["step_json_null"].body_present is True
    assert by_key["step_json_null"].body is None
    assert by_key["step_json_null"].body_sql_null is False

    assert by_key["step_empty_object"].body_present is True
    assert by_key["step_empty_object"].body == {}
    assert by_key["step_empty_object"].body_sql_null is False

    assert by_key["step_empty_array"].body_present is True
    assert by_key["step_empty_array"].body == []
    assert by_key["step_empty_array"].body_sql_null is False


async def test_a_plan_change_between_gate_and_copy_is_refused(
    fixtures, stack, monkeypatch
) -> None:
    """A writer committing after the gate but before the copy cannot slip in.

    The wrapper opens its own session, changes the source step and commits, then
    lets the create continue.  The post-copy fingerprint check must roll the
    whole transaction back: no run, no snapshot of mixed content.
    """
    await _seed_environment(fixtures, stack["project"])
    await fixtures.commit()
    public_id = await _project_public_id(fixtures, stack["project"])
    payload = RunCreateRequest.model_validate(_run_body(public_id))
    await persist_approved_plan(
        fixtures.session,
        project_id=stack["project"],
        payload=payload,
        project_public_id=public_id,
    )
    await fixtures.commit()

    original = runs._load_plan_tree

    async def mutate_then_load(session, plan_id):
        async with AsyncSessionLocal() as other:
            step = (
                await other.execute(
                    select(TestStep)
                    .join(TestScenario, TestScenario.id == TestStep.scenario_id)
                    .where(TestScenario.plan_id == plan_id, TestStep.step_key == READ_STEP)
                )
            ).scalar_one()
            config = dict(step.config or {})
            config["path"] = "/committed-mid-create"
            await other.execute(
                update(TestStep).where(TestStep.id == step.id).values(config=config)
            )
            await other.commit()
        return await original(session, plan_id)

    monkeypatch.setattr(runs, "_load_plan_tree", mutate_then_load)

    async def _do_not_schedule(run_id):
        return None

    monkeypatch.setattr(run_executor, "schedule_run", _do_not_schedule)

    with pytest.raises(AppError) as caught:
        await runs.create_run(fixtures.session, project_id=public_id, payload=payload)
    assert caught.value.code == "plan-changed"

    run_count = (
        await fixtures.session.execute(
            select(func.count()).select_from(_TestRun).where(
                _TestRun.project_id == stack["project"]
            )
        )
    ).scalar_one()
    assert run_count == 0


async def test_snapshot_columns_and_defaults_exist(read_session) -> None:
    result = (
        await read_session.execute(
            text(
                "select table_name, column_name, column_default, is_nullable "
                "from information_schema.columns "
                "where table_schema = 'public' and ( "
                "  (table_name = 'run_steps' and column_name in ('produces','body','body_present')) "
                "  or (table_name = 'test_runs' and column_name = 'snapshot_version')"
                ")"
            )
        )
    ).all()
    found = {(row.table_name, row.column_name): row for row in result}
    assert set(found) == {
        ("run_steps", "produces"),
        ("run_steps", "body"),
        ("run_steps", "body_present"),
        ("test_runs", "snapshot_version"),
    }
    assert found[("test_runs", "snapshot_version")].column_default == "1"
    assert found[("test_runs", "snapshot_version")].is_nullable == "NO"
    assert found[("run_steps", "body_present")].column_default == "false"
    assert found[("run_steps", "body_present")].is_nullable == "NO"
    assert found[("run_steps", "produces")].is_nullable == "YES"
    assert found[("run_steps", "body")].is_nullable == "YES"


async def test_a_directly_created_run_defaults_to_v1(fixtures, stack) -> None:
    run_id = await fixtures.run(stack)
    await fixtures.commit()

    stored = (
        await fixtures.session.execute(select(_TestRun).where(_TestRun.id == run_id))
    ).scalar_one()
    assert stored.snapshot_version == 1


# --------------------------------------------------------------------------- #
# The snapshot verifier reads the Run rows, not the plan
# --------------------------------------------------------------------------- #


async def _approved_snapshot(fixtures, stack, run_id: uuid.UUID):
    plan_row = (
        await fixtures.session.execute(
            select(TestPlan).where(
                TestPlan.project_id == stack["project"], TestPlan.public_id == PLAN_ID
            )
        )
    ).scalar_one()
    public_id = await _project_public_id(fixtures, stack["project"])
    stored = await plan_hash.load_stored_plan(
        fixtures.session, plan=plan_row, project_public_id=public_id
    )
    content = await plan_hash.load_run_content(
        fixtures.session,
        run_id=run_id,
        consumes_by_step=runs._consumes_by_step(stored.payload),
    )
    return stored, content


async def test_run_row_hash_matches_the_approval(fixtures, stack, monkeypatch) -> None:
    plan = _with_body_and_source()
    run_id = await _create_run(fixtures, stack, monkeypatch, plan=plan)
    stored, content = await _approved_snapshot(fixtures, stack, run_id)

    assert plan_hash.hash_content(content) == stored.content_hash


async def test_tampered_step_fields_break_the_snapshot_digest(
    fixtures, stack, monkeypatch
) -> None:
    plan = _with_body_and_source()
    run_id = await _create_run(fixtures, stack, monkeypatch, plan=plan)
    stored, content = await _approved_snapshot(fixtures, stack, run_id)
    assert plan_hash.hash_content(content) == stored.content_hash

    step = (await _run_steps(fixtures, run_id))[READ_STEP]
    mutations = [
        ("method", "PATCH"),
        ("path", "/tampered"),
        ("body", {"tampered": True}),
        ("body_present", False),
        ("produces", "tampered_var"),
    ]
    for field, value in mutations:
        original = getattr(step, field)
        setattr(step, field, value)
        await fixtures.session.flush()
        _stored, changed = await _approved_snapshot(fixtures, stack, run_id)
        assert plan_hash.hash_content(changed) != stored.content_hash, (
            "tampering " + field + " did not change the rebuilt run digest"
        )
        setattr(step, field, original)
        await fixtures.session.flush()


async def test_tampered_assertion_breaks_the_snapshot_digest(
    fixtures, stack, monkeypatch
) -> None:
    from backend.db.models.result import RunAssertion

    plan = _with_body_and_source()
    run_id = await _create_run(fixtures, stack, monkeypatch, plan=plan)
    stored, content = await _approved_snapshot(fixtures, stack, run_id)
    assert plan_hash.hash_content(content) == stored.content_hash

    assertion = (
        await fixtures.session.execute(
            select(RunAssertion)
            .join(RunScenario, RunScenario.id == RunAssertion.run_scenario_id)
            .where(RunScenario.run_id == run_id)
        )
    ).scalars().first()
    assert assertion is not None

    mutations = [
        ("target", "body.tampered"),
        ("expected_value", "999"),
        ("assertion_type", "header"),
        ("run_step_id", None),
    ]
    for field, value in mutations:
        original = getattr(assertion, field)
        setattr(assertion, field, value)
        await fixtures.session.flush()
        _stored, changed = await _approved_snapshot(fixtures, stack, run_id)
        assert plan_hash.hash_content(changed) != stored.content_hash, (
            "tampering assertion " + field + " did not change the rebuilt run digest"
        )
        setattr(assertion, field, original)
        await fixtures.session.flush()


async def test_reordered_run_steps_break_the_snapshot_digest(
    fixtures, stack, monkeypatch
) -> None:
    plan = _with_body_and_source()
    run_id = await _create_run(fixtures, stack, monkeypatch, plan=plan)
    stored, content = await _approved_snapshot(fixtures, stack, run_id)
    assert plan_hash.hash_content(content) == stored.content_hash

    steps = await _run_steps(fixtures, run_id)
    first, second = steps[READ_STEP], steps[CREATE_STEP]
    first_order = first.sort_order
    second_order = second.sort_order
    first.sort_order, second.sort_order = second_order, first_order
    await fixtures.session.flush()

    _stored, changed = await _approved_snapshot(fixtures, stack, run_id)
    assert plan_hash.hash_content(changed) != stored.content_hash


async def test_a_snapshot_mismatch_rolls_the_whole_create_back(
    fixtures, stack, monkeypatch
) -> None:
    await _seed_environment(fixtures, stack["project"])
    await fixtures.commit()
    public_id = await _project_public_id(fixtures, stack["project"])
    payload = RunCreateRequest.model_validate(_run_body(public_id))
    await persist_approved_plan(
        fixtures.session,
        project_id=stack["project"],
        payload=payload,
        project_public_id=public_id,
    )
    await fixtures.commit()

    original = runs._insert_run_tree

    async def tamper_after_insert(session, *, run, plan, materialization):
        await original(session, run=run, plan=plan, materialization=materialization)
        run_step = (
            await session.execute(
                select(RunStep)
                .join(RunScenario, RunScenario.id == RunStep.run_scenario_id)
                .where(RunScenario.run_id == run.id)
                .order_by(RunStep.sort_order)
            )
        ).scalars().first()
        assert run_step is not None
        run_step.body_present = True
        run_step.body = {"tampered": True}
        await session.flush()

    monkeypatch.setattr(runs, "_insert_run_tree", tamper_after_insert)

    async def _do_not_schedule(run_id):
        return None

    monkeypatch.setattr(run_executor, "schedule_run", _do_not_schedule)

    with pytest.raises(AppError) as caught:
        await runs.create_run(fixtures.session, project_id=public_id, payload=payload)
    assert caught.value.code == "run-snapshot-mismatch"

    run_count = (
        await fixtures.session.execute(
            select(func.count()).select_from(_TestRun).where(
                _TestRun.project_id == stack["project"]
            )
        )
    ).scalar_one()
    assert run_count == 0
