"""The executor's last defense against a structurally empty Run.

A version-1 snapshot can still be corrupted or produced by an older writer.
These tests build that state on top of a real run and prove the executor fails
before the wire instead of recording a green run that tested nothing.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from backend.db.models.result import RunEvent, RunScenario, RunStep, TestRun
from backend.services import run_executor

from tests.test_run_execution import _create_run, _install_client

pytestmark = pytest.mark.anyio


async def _events(fixtures, run_id: uuid.UUID) -> list[RunEvent]:
    return (
        await fixtures.session.execute(
            select(RunEvent)
            .where(RunEvent.run_id == run_id)
            .order_by(RunEvent.seq)
        )
    ).scalars().all()


async def _remove_all_scenarios(fixtures, run_id: uuid.UUID) -> None:
    await fixtures.session.execute(
        delete(RunScenario).where(RunScenario.run_id == run_id)
    )
    await fixtures.session.commit()


async def _remove_all_steps(fixtures, run_id: uuid.UUID) -> None:
    scenario_ids = select(RunScenario.id).where(RunScenario.run_id == run_id)
    await fixtures.session.execute(
        delete(RunStep).where(RunStep.run_scenario_id.in_(scenario_ids))
    )
    await fixtures.session.commit()


async def _remove_request_steps(fixtures, run_id: uuid.UUID) -> None:
    scenario_ids = select(RunScenario.id).where(RunScenario.run_id == run_id)
    await fixtures.session.execute(
        delete(RunStep).where(
            RunStep.run_scenario_id.in_(scenario_ids),
            RunStep.step_type == "request",
        )
    )
    await fixtures.session.commit()


async def _assert_empty_failure(fixtures, run_id, client) -> None:
    assert client.sent == []
    run = await fixtures.session.get(TestRun, run_id)
    assert run is not None
    await fixtures.session.refresh(run)
    assert run.status == "failed"
    assert run.error_code == run_executor.EMPTY_EXECUTION_TREE

    events = await _events(fixtures, run_id)
    types = [event.event_type for event in events]
    assert "run.failed" in types
    assert "run.completed" not in types
    assert "run.started" not in types


async def test_a_v1_run_with_no_scenarios_fails_instead_of_passing(
    fixtures, stack, monkeypatch
) -> None:
    run_id = await _create_run(fixtures, stack, monkeypatch)
    await _remove_all_scenarios(fixtures, run_id)

    client = _install_client(monkeypatch)
    await run_executor.execute_run(run_id)

    await _assert_empty_failure(fixtures, run_id, client)


async def test_a_v1_scenario_without_steps_fails_instead_of_passing(
    fixtures, stack, monkeypatch
) -> None:
    run_id = await _create_run(fixtures, stack, monkeypatch)
    await _remove_all_steps(fixtures, run_id)

    client = _install_client(monkeypatch)
    await run_executor.execute_run(run_id)

    await _assert_empty_failure(fixtures, run_id, client)


async def test_a_v1_scenario_without_a_request_step_fails(
    fixtures, stack, monkeypatch
) -> None:
    run_id = await _create_run(fixtures, stack, monkeypatch)
    await _remove_request_steps(fixtures, run_id)

    client = _install_client(monkeypatch)
    await run_executor.execute_run(run_id)

    await _assert_empty_failure(fixtures, run_id, client)
