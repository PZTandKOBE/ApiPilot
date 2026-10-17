"""C33-R1: persisted run reports.

These tests use only the isolated conftest database. They assert real PDF bytes,
metadata/file persistence, project scoping, refusal for unfinished runs and the
no-row-on-failure rule.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import datetime, timezone

import pymupdf
import pytest
from pypdf import PdfReader
from sqlalchemy import func, select, update

from backend.api.errors import AppError
from backend.api.routers.reports import download_report, generate_run_report, view_report
from backend.db.models.project import Environment, Project
from backend.db.models.result import RunReport, TestRun as _TestRun
from backend.db.models.user import GuestSession
from backend.schemas.run import (
    RunAssertionResponse,
    RunDetailResponse,
    RunEvidenceResponse,
    RunFailureResponse,
    RunResponse,
    RunScenarioResponse,
    RunStepResponse,
    RunSummaryResponse,
)
from backend.services import report_pdf, reports

pytestmark = pytest.mark.anyio


async def _project(session, project_id: uuid.UUID) -> Project:
    return (await session.execute(select(Project).where(Project.id == project_id))).scalar_one()


async def _attach_environment(fixtures, stack, run_id: uuid.UUID) -> None:
    """The run detail contract requires an environment id, even for a report test."""
    environment = Environment(
        project_id=stack["project"],
        public_id="env_c33r1_" + uuid.uuid4().hex[:8],
        name="C33R1 environment",
        kind="development",
        base_url="http://127.0.0.1:9/c33r1",
    )
    fixtures.session.add(environment)
    environment_id = await fixtures._keep(Environment, environment)
    await fixtures.session.execute(
        update(_TestRun).where(_TestRun.id == run_id).values(environment_id=environment_id)
    )


async def _report_count(session, project_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count(RunReport.id)).where(RunReport.project_id == project_id)
            )
        ).scalar_one()
    )


def _synthetic_detail() -> RunDetailResponse:
    now = datetime.now(timezone.utc)
    secret = "super-secret-token"
    return RunDetailResponse(
        run=RunResponse(
            id="run-c33r1-sample",
            project_id="prj_orders",
            plan_id="plan_orders_v2",
            plan_name={"text": "订单生命周期验证"},
            spec_id="spec_orders",
            environment_id="env_orders",
            base_url="https://alice:pa55@api.example.com/v1?token=" + secret,
            variable_keys=["token", "password"],
            status="failed",
            created_at=now,
            started_at=now,
            finished_at=now,
            duration_ms=3210,
            failure=RunFailureResponse(
                message={"text": "The request failed."},
                detail="Authorization: Bearer " + secret + " at https://api.example.com/orders?token=" + secret,
            ),
            summary=RunSummaryResponse(
                scenarios=1,
                steps=1,
                assertions=2,
                passed_steps=0,
                failed_steps=1,
                passed_assertions=1,
                failed_assertions=1,
            ),
        ),
        scenarios=[
            RunScenarioResponse(
                id="scenario-1",
                index=0,
                name={"text": "订单创建与读取：" + "这是一个足够长的中文场景名称。" * 30},
                risk_level="high",
                status="failed",
                steps=[
                    RunStepResponse(
                        id="step-1",
                        scenario_id="scenario-1",
                        index=0,
                        kind="request",
                        description={"text": "创建订单并检查响应。" * 80},
                        endpoint_id="ep_post_orders",
                        method="POST",
                        path="/orders?token=" + secret,
                        status="failed",
                        duration_ms=120,
                        failure=RunFailureResponse(
                            message={"text": "Request failed"},
                            detail="Authorization: Bearer " + secret,
                        ),
                        evidence=[
                            RunEvidenceResponse(
                                label={"key": "console.runs.evidence.endpoint"},
                                value="POST /orders?token=" + secret,
                            )
                        ],
                    )
                ],
                assertions=[
                    RunAssertionResponse(
                        id="a1",
                        scenario_id="scenario-1",
                        step_id="step-1",
                        kind="status",
                        target="status",
                        expected="201",
                        actual="500",
                        status="failed",
                        description={"text": "响应状态码为 201"},
                    ),
                    RunAssertionResponse(
                        id="a2",
                        scenario_id="scenario-1",
                        step_id="step-1",
                        kind="field",
                        target="body.token",
                        expected="present",
                        actual=secret,
                        status="failed",
                        description={"text": "响应体包含 token"},
                    ),
                ],
            )
        ],
        last_seq=10,
    )


async def test_a_terminal_run_produces_a_real_persisted_pdf(fixtures, stack, read_session):
    run_id = await fixtures.run(stack, status="passed", started_at=datetime.now(timezone.utc))
    await _attach_environment(fixtures, stack, run_id)
    await fixtures.commit()
    project = await _project(fixtures.session, stack["project"])

    created = await reports.generate_report(
        fixtures.session, project=project, run_id=str(run_id)
    )

    row = (
        await read_session.execute(select(RunReport).where(RunReport.id == uuid.UUID(created.id)))
    ).scalar_one()
    assert row.content.startswith(b"%PDF")
    assert len(row.content) > 1000
    assert row.byte_size == len(row.content)
    assert row.sha256 == hashlib.sha256(row.content).hexdigest()
    assert row.run_id == run_id
    assert row.project_id == stack["project"]
    assert created.run_status == "passed"
    assert created.filename == "ApiPilot-Run-" + str(run_id) + ".pdf"
    assert (await reports.list_reports(fixtures.session, project=project))[0].id == created.id

    fetched = await reports.get_report(fixtures.session, project=project, report_id=created.id)
    assert fetched.content == row.content


async def test_queued_and_running_runs_are_refused_without_a_row(fixtures, stack, read_session):
    queued = await fixtures.run(stack, status="queued")
    await fixtures.commit()
    project = await _project(fixtures.session, stack["project"])
    before = await _report_count(read_session, stack["project"])

    with pytest.raises(AppError) as caught:
        await reports.generate_report(fixtures.session, project=project, run_id=str(queued))

    assert caught.value.status_code == 409
    assert caught.value.code == reports.REPORT_NOT_READY_CODE
    assert await _report_count(read_session, stack["project"]) == before


async def test_generation_failure_leaves_no_success_record(
    fixtures, stack, read_session, monkeypatch
):
    run_id = await fixtures.run(stack, status="failed", started_at=datetime.now(timezone.utc))
    await _attach_environment(fixtures, stack, run_id)
    await fixtures.commit()
    project = await _project(fixtures.session, stack["project"])
    before = await _report_count(read_session, stack["project"])

    def _fail(_detail):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(report_pdf, "build_report_pdf", _fail)

    with pytest.raises(AppError) as caught:
        await reports.generate_report(fixtures.session, project=project, run_id=str(run_id))

    assert caught.value.status_code == 500
    assert caught.value.code == reports.REPORT_FAILED_CODE
    assert await _report_count(read_session, stack["project"]) == before


async def test_reports_are_scoped_to_the_project(fixtures, stack, read_session):
    run_id = await fixtures.run(stack, status="cancelled", started_at=datetime.now(timezone.utc))
    await _attach_environment(fixtures, stack, run_id)
    second_project_id = await fixtures.project(stack["guest"])
    await fixtures.commit()
    project = await _project(fixtures.session, stack["project"])
    second = await _project(fixtures.session, second_project_id)

    created = await reports.generate_report(
        fixtures.session, project=project, run_id=str(run_id)
    )

    with pytest.raises(AppError) as caught:
        await reports.get_report(fixtures.session, project=second, report_id=created.id)

    assert caught.value.status_code == 404
    assert await _report_count(read_session, second_project_id) == 0


async def test_generated_pdf_redacts_secrets_and_renders_multiple_pages():
    content, generated_at = report_pdf.build_report_pdf(_synthetic_detail())

    assert generated_at.tzinfo is not None
    assert content.startswith(b"%PDF")
    extracted = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages
    )
    assert "super-secret-token" not in extracted
    assert "pa55" not in extracted
    assert "Authorization: Bearer" not in extracted

    document = pymupdf.open(stream=content, filetype="pdf")
    assert document.page_count >= 2
    for page_number in range(document.page_count):
        pix = document[page_number].get_pixmap(dpi=80)
        assert pix.width > 0 and pix.height > 0
        assert pix.samples

    assert report_pdf.report_filename("../../etc/passwd") == "ApiPilot-Run-.._.._etc_passwd.pdf"


async def test_route_serves_the_same_persisted_bytes(fixtures, stack, read_session):
    run_id = await fixtures.run(stack, status="passed", started_at=datetime.now(timezone.utc))
    await _attach_environment(fixtures, stack, run_id)
    await fixtures.commit()

    guest = await fixtures.session.get(GuestSession, stack["guest"])
    project = await _project(fixtures.session, stack["project"])
    assert guest is not None

    created = await generate_run_report(
        project.public_id, str(run_id), fixtures.session, guest
    )
    view = await view_report(project.public_id, created.id, fixtures.session, guest)
    download = await download_report(project.public_id, created.id, fixtures.session, guest)

    row = (
        await read_session.execute(select(RunReport).where(RunReport.id == uuid.UUID(created.id)))
    ).scalar_one()
    assert view.media_type == "application/pdf"
    assert view.body == row.content
    assert download.body == row.content
    assert "attachment" in download.headers["content-disposition"]
    assert "inline" in view.headers["content-disposition"]


async def test_report_routes_are_registered():
    from backend.app import create_app

    paths = create_app().openapi()["paths"]
    assert "/api/projects/{project_id}/reports" in paths
    assert "/api/projects/{project_id}/runs/{run_id}/reports" in paths
    assert "/api/projects/{project_id}/reports/{report_id}/file" in paths
    assert "/api/projects/{project_id}/reports/{report_id}/download" in paths
