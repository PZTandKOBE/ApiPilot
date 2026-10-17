"""Generate, list and read persisted PDF reports for finished runs."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import AppError
from backend.db.models.project import Project
from backend.db.models.result import RunReport, TestRun
from backend.schemas.report import RunReportResponse
from backend.services import report_pdf, runs

__all__ = [
    "generate_report",
    "get_report",
    "list_reports",
]

logger = logging.getLogger(__name__)

REPORT_NOT_FOUND_CODE = "report-not-found"
REPORT_NOT_FOUND_KEY = "console.report.notFound"
REPORT_NOT_READY_CODE = "report-not-ready"
REPORT_NOT_READY_KEY = "console.report.notReady"
REPORT_FAILED_CODE = "report-generation-failed"
REPORT_FAILED_KEY = "console.report.generateFailed"

_TERMINAL = frozenset({"passed", "failed", "cancelled"})


def _report_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


def _not_found(report_id: str) -> AppError:
    return AppError(
        404,
        code=REPORT_NOT_FOUND_CODE,
        message_key=REPORT_NOT_FOUND_KEY,
        params={"reportId": report_id},
    )


def _response(report: RunReport, run_status: str) -> RunReportResponse:
    return RunReportResponse(
        id=str(report.id),
        project_id=str(report.project_id),
        run_id=str(report.run_id),
        name=report.name,
        filename=report.filename,
        content_type=report.content_type,
        byte_size=report.byte_size,
        sha256=report.sha256,
        generated_at=report.created_at,
        run_status=run_status,
    )


async def generate_report(
    session: AsyncSession, *, project: Project, run_id: str
) -> RunReportResponse:
    """Render and persist one PDF, or leave no success row behind.

    The PDF is built entirely in memory first. The database insert happens only
    after the renderer returned a non-empty PDF signature, so a failed renderer
    cannot leave a metadata row that claims a file exists.
    """
    parsed_run = _report_uuid(run_id)

    if parsed_run is None:
        raise AppError(
            404,
            code="run-not-found",
            message_key="console.runs.errors.notFound",
            params={"runId": run_id},
        )

    found = await session.execute(
        select(TestRun).where(
            TestRun.id == parsed_run,
            TestRun.project_id == project.id,
        )
    )
    run = found.scalar_one_or_none()

    if run is None:
        raise AppError(
            404,
            code="run-not-found",
            message_key="console.runs.errors.notFound",
            params={"runId": run_id},
        )

    if run.status not in _TERMINAL:
        raise AppError(
            409,
            code=REPORT_NOT_READY_CODE,
            message_key=REPORT_NOT_READY_KEY,
            details={"status": run.status},
        )

    detail = await runs.get_run_detail(session, run_id=run_id)

    try:
        content, generated_at = report_pdf.build_report_pdf(detail)
    except Exception:
        logger.exception("report generation failed for run %s", run_id)
        raise AppError(
            500,
            code=REPORT_FAILED_CODE,
            message_key=REPORT_FAILED_KEY,
        ) from None

    if not content.startswith(b"%PDF") or len(content) < 100:
        logger.error("report renderer returned an invalid PDF for run %s", run_id)
        raise AppError(500, code=REPORT_FAILED_CODE, message_key=REPORT_FAILED_KEY)

    row = RunReport(
        project_id=project.id,
        run_id=parsed_run,
        name=report_pdf.report_name(),
        filename=report_pdf.report_filename(run_id),
        content_type="application/pdf",
        byte_size=len(content),
        sha256=report_pdf.report_sha256(content),
        content=content,
    )

    try:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    except Exception:
        await session.rollback()
        logger.exception("report metadata insert failed for run %s", run_id)
        raise AppError(500, code=REPORT_FAILED_CODE, message_key=REPORT_FAILED_KEY) from None

    logger.info(
        "created report %s for run %s (%s bytes)",
        row.id,
        run_id,
        len(content),
    )
    return _response(row, run.status)


async def list_reports(
    session: AsyncSession, *, project: Project
) -> list[RunReportResponse]:
    """Every saved report for the project, newest first."""
    found = await session.execute(
        select(RunReport, TestRun.status)
        .join(TestRun, TestRun.id == RunReport.run_id)
        .where(RunReport.project_id == project.id)
        .order_by(RunReport.created_at.desc(), RunReport.id.desc())
    )

    return [_response(report, status) for report, status in found.all()]


async def get_report(
    session: AsyncSession, *, project: Project, report_id: str
) -> RunReport:
    """The report row, scoped to the already-authorized project."""
    parsed = _report_uuid(report_id)

    if parsed is None:
        raise _not_found(report_id)

    found = await session.execute(
        select(RunReport).where(
            RunReport.id == parsed,
            RunReport.project_id == project.id,
        )
    )
    report = found.scalar_one_or_none()

    if report is None:
        raise _not_found(report_id)

    return report
