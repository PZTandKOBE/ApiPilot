"""Deletion contracts: plan soft-delete keeps history; project hard-delete cascades.

Every test runs against the isolated conftest database and real routes over an
ASGI transport. The plan test additionally inspects the historical run tree and
the persisted PDF bytes; the project test proves the cascade stops at the
project boundary and does not touch another guest's project.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import uuid

import httpx
import pytest
from sqlalchemy import func, select, update

from backend.app import create_app
from backend.db.models.agent import AgentTask, AgentTaskAudit, TestPlan
from backend.db.models.project import (
    ApiEndpoint,
    ApiSpec,
    Environment,
    EnvironmentVariable,
    Project,
)
from backend.db.models.result import (
    ApiRequestHistory,
    RunAssertion,
    RunEvidence,
    RunReport,
    RunScenario,
    RunStep,
    TestRun,
)
from backend.db.models.user import GuestSession
from backend.services import guest_session

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def app_client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        yield client


async def issue_guest(fixtures):
    guest, token = await guest_session.issue(fixtures.session)
    await fixtures._keep(GuestSession, guest)
    await fixtures.commit()
    return guest, token


async def token_for_guest(fixtures, guest_id: uuid.UUID) -> str:
    """Reissue a usable token for the guest the stack fixture created."""
    token = guest_session.generate_token()
    await fixtures.session.execute(
        update(GuestSession)
        .where(GuestSession.id == guest_id)
        .values(token_hash=guest_session.hash_token(token))
    )
    await fixtures.commit()
    return token


async def public_id(fixtures, project_id: uuid.UUID) -> str:
    return (
        await fixtures.session.execute(
            select(Project.public_id).where(Project.id == project_id)
        )
    ).scalar_one()


async def make_report(fixtures, project_id: uuid.UUID, run_id: uuid.UUID) -> RunReport:
    content = b"%PDF-1.4\nhistorical report\n%%EOF"
    report = RunReport(
        project_id=project_id,
        run_id=run_id,
        name="Historical report",
        filename="historical.pdf",
        content_type="application/pdf",
        byte_size=len(content),
        sha256="0" * 64,
        content=content,
    )
    fixtures.session.add(report)
    await fixtures._keep(RunReport, report)
    await fixtures.commit()
    return report


async def add_history(fixtures, stack) -> TestRun:
    now = datetime.now(timezone.utc)
    environment = stack.get("environment")
    if environment is None:
        environment = await fixtures.environment(
            stack["project"],
            name="History environment",
            public_id="env_history",
        )
        stack["environment"] = environment

    run = TestRun(
        project_id=stack["project"],
        plan_id=stack["plan"],
        spec_id=stack["spec"],
        environment_id=environment,
        plan_name={"text": "Historical plan"},
        base_url="http://127.0.0.1:9/history",
        status="passed",
        started_at=now,
        finished_at=now,
    )
    fixtures.session.add(run)
    await fixtures.session.flush()

    scenario = RunScenario(
        run_id=run.id,
        source_scenario_id=None,
        scenario_key="scenario_history",
        name={"text": "Historical scenario"},
        risk_level="low",
        sort_order=0,
        status="passed",
    )
    fixtures.session.add(scenario)
    await fixtures.session.flush()

    step = RunStep(
        run_scenario_id=scenario.id,
        source_step_id=None,
        step_key="step_history",
        description={"text": "Historical request"},
        step_type="request",
        method="GET",
        path="/history",
        sort_order=0,
        status="passed",
    )
    fixtures.session.add(step)
    await fixtures.session.flush()

    fixtures.session.add_all(
        [
            RunAssertion(
                run_scenario_id=scenario.id,
                run_step_id=step.id,
                assertion_key="assert_history",
                assertion_type="status",
                target="status",
                expected_value=200,
                actual_value=200,
                status="passed",
            ),
            RunEvidence(
                run_id=run.id,
                run_step_id=step.id,
                evidence_type="checked",
                label={"text": "Historical evidence"},
                value="200",
            ),
        ]
    )
    await fixtures.session.flush()
    await fixtures._keep(TestRun, run)
    await fixtures.commit()
    return run


async def create_plan_version(
    fixtures,
    project_id: uuid.UUID,
    spec_id: uuid.UUID,
    *,
    public_id: str,
    version: int,
    name: str = "Second version",
) -> TestPlan:
    plan = TestPlan(
        project_id=project_id,
        spec_id=spec_id,
        public_id=public_id,
        version=version,
        name={"text": name},
        description={"text": "Historical version"},
        status="draft",
        risk_level="low",
        source="generated",
    )
    fixtures.session.add(plan)
    await fixtures._keep(TestPlan, plan)
    await fixtures.commit()
    return plan


async def test_plan_delete_soft_retires_versions_and_keeps_history(fixtures, stack):
    app = create_app()
    token = await token_for_guest(fixtures, stack["guest"])
    project = stack["project"]
    project_public = await public_id(fixtures, project)
    first = (
        await fixtures.session.execute(select(TestPlan).where(TestPlan.id == stack["plan"]))
    ).scalar_one()
    second = await create_plan_version(
        fixtures,
        project,
        stack["spec"],
        public_id=first.public_id + "_v2",
        version=2,
    )

    other_spec = await fixtures.spec(project, name="Another API", slug="another_api_spec")
    other_plan = await fixtures.plan(project, other_spec)
    await fixtures.commit()

    run = await add_history(fixtures, stack)
    report = await make_report(fixtures, project, run.id)

    async with app_client(app) as client:
        response = await client.delete(
            "/api/projects/" + project_public + "/plans/" + first.public_id,
            headers={"X-Guest-Session": token},
        )
        listed = await client.get(
            "/api/projects/" + project_public + "/plans",
            headers={"X-Guest-Session": token},
        )
        history = await client.get(
            "/api/runs/" + str(run.id),
            headers={"X-Guest-Session": token},
        )
        reports = await client.get(
            "/api/projects/" + project_public + "/reports",
            headers={"X-Guest-Session": token},
        )
        pdf = await client.get(
            "/api/projects/" + project_public + "/reports/" + str(report.id) + "/file",
            headers={"X-Guest-Session": token},
        )
        again = await client.delete(
            "/api/projects/" + project_public + "/plans/" + first.public_id,
            headers={"X-Guest-Session": token},
        )

    assert response.status_code == 204
    assert again.status_code == 404

    rows = (
        await fixtures.session.execute(
            select(TestPlan.id, TestPlan.public_id, TestPlan.deleted_at).where(
                TestPlan.id.in_([first.id, second.id, other_plan])
            )
        )
    ).all()
    by_id = {row.id: row for row in rows}
    assert by_id[first.id].deleted_at is not None
    assert by_id[second.id].deleted_at is not None
    assert by_id[other_plan].deleted_at is None

    plan_list = listed.json()
    assert all(item["id"] != first.public_id and item["id"] != second.public_id for item in plan_list)
    assert any(item["id"] == by_id[other_plan].public_id for item in plan_list)

    assert history.status_code == 200
    assert history.json()["run"]["id"] == str(run.id)
    assert history.json()["run"]["planId"] == first.public_id
    assert history.json()["scenarios"][0]["steps"][0]["path"] == "/history"

    assert reports.status_code == 200
    assert reports.json()[0]["id"] == str(report.id)
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-1.4")

    assert (
        await fixtures.session.execute(
            select(RunReport.id).where(RunReport.id == report.id)
        )
    ).scalar_one() == report.id
    assert (
        await fixtures.session.execute(
            select(RunReport.content).where(RunReport.id == report.id)
        )
    ).scalar_one().startswith(b"%PDF-1.4")
    scenario_id = (
        await fixtures.session.execute(
            select(RunScenario.id).where(RunScenario.run_id == run.id)
        )
    ).scalar_one()
    assert (
        await fixtures.session.execute(
            select(func.count()).select_from(RunStep).where(RunStep.run_scenario_id == scenario_id)
        )
    ).scalar_one() == 1
    assert (
        await fixtures.session.execute(
            select(func.count()).select_from(RunAssertion).where(
                RunAssertion.run_scenario_id == scenario_id
            )
        )
    ).scalar_one() == 1
    assert (
        await fixtures.session.execute(
            select(func.count()).select_from(RunEvidence).where(RunEvidence.run_id == run.id)
        )
    ).scalar_one() == 1


async def test_plan_delete_rejects_foreign_guest(fixtures, stack):
    app = create_app()
    project_public = await public_id(fixtures, stack["project"])
    plan = (
        await fixtures.session.execute(select(TestPlan).where(TestPlan.id == stack["plan"]))
    ).scalar_one()
    other_guest, other_token = await issue_guest(fixtures)

    async with app_client(app) as client:
        response = await client.delete(
            "/api/projects/" + project_public + "/plans/" + plan.public_id,
            headers={"X-Guest-Session": other_token},
        )
        missing = await client.delete(
            "/api/projects/" + project_public + "/plans/plan_does_not_exist",
            headers={"X-Guest-Session": other_token},
        )

    assert response.status_code == 404
    assert missing.status_code == 404
    assert (await fixtures.session.execute(
        select(TestPlan.id).where(TestPlan.id == plan.id, TestPlan.deleted_at.is_(None))
    )).scalar_one() == plan.id
    assert other_guest != stack["guest"]


async def test_project_delete_cascades_only_its_own_data(fixtures, stack):
    app = create_app()
    token = await token_for_guest(fixtures, stack["guest"])
    project = stack["project"]
    project_public = await public_id(fixtures, project)

    environment = await fixtures.environment(project, name="Delete me")
    stack["environment"] = environment
    variable = await fixtures.environment_variable(environment, key="secret", value="value")
    endpoint = await fixtures.endpoint(stack["spec"])
    task = await fixtures.agent_task(project, stack["spec"])
    fixtures.session.add(
        AgentTaskAudit(task_id=task, status="completed", understanding={"specId": "spec_history"})
    )
    await fixtures.session.flush()

    plan = (
        await fixtures.session.execute(select(TestPlan).where(TestPlan.id == stack["plan"]))
    ).scalar_one()
    run = await add_history(fixtures, stack)
    report = await make_report(fixtures, project, run.id)
    history_entry = ApiRequestHistory(
        project_id=project,
        method="GET",
        request_url="https://example.test/history",
    )
    fixtures.session.add(history_entry)
    await fixtures.session.flush()

    other_guest, other_token = await issue_guest(fixtures)
    other_project = await fixtures.project(other_guest.id)
    other_spec = await fixtures.spec(other_project, name="Other project spec")
    other_plan = await fixtures.plan(other_project, other_spec)
    await fixtures.commit()

    async with app_client(app) as client:
        forbidden = await client.delete(
            "/api/projects/" + project_public,
            headers={"X-Guest-Session": other_token},
        )
        response = await client.delete(
            "/api/projects/" + project_public,
            headers={"X-Guest-Session": token},
        )
        listed = await client.get("/api/projects", headers={"X-Guest-Session": token})
        again = await client.delete(
            "/api/projects/" + project_public,
            headers={"X-Guest-Session": token},
        )

    # Re-establish the same verified identity in a fresh request context: a
    # browser refresh is exactly this, and the deleted project must stay gone.
    async with app_client(app) as refreshed_client:
        refreshed = await refreshed_client.get(
            "/api/projects", headers={"X-Guest-Session": token}
        )
        refreshed_again = await refreshed_client.get(
            "/api/projects", headers={"X-Guest-Session": token}
        )

    assert forbidden.status_code == 404
    assert response.status_code == 204
    assert again.status_code == 404
    assert all(item["id"] != project_public for item in listed.json())
    assert all(item["id"] != project_public for item in refreshed.json())
    assert all(item["id"] != project_public for item in refreshed_again.json())

    assert (
        await fixtures.session.execute(select(Project.id).where(Project.id == project))
    ).scalar_one_or_none() is None
    for model, row_id in [
        (Environment, environment),
        (EnvironmentVariable, variable),
        (ApiEndpoint, endpoint),
        (AgentTask, task),
        (ApiRequestHistory, history_entry.id),
        (TestPlan, plan.id),
        (TestRun, run.id),
        (RunReport, report.id),
    ]:
        assert (
            await fixtures.session.execute(select(model.id).where(model.id == row_id))
        ).scalar_one_or_none() is None

    assert (
        await fixtures.session.execute(
            select(AgentTaskAudit.id).where(AgentTaskAudit.task_id == task)
        )
    ).scalar_one_or_none() is None
    scenario_ids = select(RunScenario.id).where(RunScenario.run_id == run.id)
    assert (
        await fixtures.session.execute(
            select(func.count()).select_from(RunScenario).where(RunScenario.run_id == run.id)
        )
    ).scalar_one() == 0
    assert (
        await fixtures.session.execute(
            select(func.count()).select_from(RunStep).where(RunStep.run_scenario_id.in_(scenario_ids))
        )
    ).scalar_one() == 0
    assert (
        await fixtures.session.execute(
            select(func.count()).select_from(RunAssertion).where(
                RunAssertion.run_scenario_id.in_(scenario_ids)
            )
        )
    ).scalar_one() == 0
    assert (
        await fixtures.session.execute(
            select(func.count()).select_from(RunEvidence).where(RunEvidence.run_id == run.id)
        )
    ).scalar_one() == 0
    assert (
        await fixtures.session.execute(select(ApiSpec.id).where(ApiSpec.id == stack["spec"]))
    ).scalar_one_or_none() is None
    assert (
        await fixtures.session.execute(select(GuestSession.id).where(GuestSession.id == stack["guest"]))
    ).scalar_one_or_none() == stack["guest"]

    # The other guest's project, spec and plan are untouched.
    assert (
        await fixtures.session.execute(select(Project.id).where(Project.id == other_project))
    ).scalar_one() == other_project
    assert (
        await fixtures.session.execute(select(ApiSpec.id).where(ApiSpec.id == other_spec))
    ).scalar_one() == other_spec
    assert (
        await fixtures.session.execute(select(TestPlan.id).where(TestPlan.id == other_plan))
    ).scalar_one() == other_plan
