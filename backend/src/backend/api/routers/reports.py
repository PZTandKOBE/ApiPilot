"""Persisted PDF report routes.

A report is addressed by its own UUID.  There is no filesystem path in the URL
and no user-controlled filename in the response, so the download route has no
path-traversal surface; project ownership is checked before the row is read.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from backend.api.deps import CurrentGuestSessionDep, SessionDep
from backend.api.errors import ERROR_RESPONSES
from backend.db.models.result import RunReport
from backend.schemas.report import RunReportResponse
from backend.services import guest_access, reports

__all__ = ["router"]

router = APIRouter(prefix="/api", tags=["reports"])

ProjectId = Annotated[
    str,
    Path(description="The project's public_id, e.g. prj_orders.", examples=["prj_orders"]),
]
RunId = Annotated[
    str,
    Path(description="The run's UUID.", examples=["6f1c1f4e-4a4e-4e2a-9f0e-3a1d2b3c4d5e"]),
]
ReportId = Annotated[
    str,
    Path(description="The saved report's UUID.", examples=["8a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"]),
]


@router.post(
    "/projects/{project_id}/runs/{run_id}/reports",
    response_model=RunReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate and save a PDF report for a finished run",
    responses=ERROR_RESPONSES,
)
async def generate_run_report(
    project_id: ProjectId,
    run_id: RunId,
    session: SessionDep,
    guest: CurrentGuestSessionDep,
) -> RunReportResponse:
    project = await guest_access.require_guest_project_access(
        session, project_public_id=project_id, guest=guest
    )

    return await reports.generate_report(session, project=project, run_id=run_id)


@router.get(
    "/projects/{project_id}/reports",
    response_model=list[RunReportResponse],
    summary="List saved reports in a project",
    responses=ERROR_RESPONSES,
)
async def list_project_reports(
    project_id: ProjectId,
    session: SessionDep,
    guest: CurrentGuestSessionDep,
) -> list[RunReportResponse]:
    project = await guest_access.require_guest_project_access(
        session, project_public_id=project_id, guest=guest
    )

    return await reports.list_reports(session, project=project)


def _pdf_response(report: RunReport, *, attachment: bool) -> Response:
    filename = report.filename
    content = report.content
    disposition = "attachment" if attachment else "inline"

    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Content-Length": str(len(content)),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/projects/{project_id}/reports/{report_id}/file",
    summary="View a saved report PDF",
    responses=ERROR_RESPONSES,
)
async def view_report(
    project_id: ProjectId,
    report_id: ReportId,
    session: SessionDep,
    guest: CurrentGuestSessionDep,
) -> Response:
    project = await guest_access.require_guest_project_access(
        session, project_public_id=project_id, guest=guest
    )
    report = await reports.get_report(session, project=project, report_id=report_id)

    return _pdf_response(report, attachment=False)


@router.get(
    "/projects/{project_id}/reports/{report_id}/download",
    summary="Download a saved report PDF",
    responses=ERROR_RESPONSES,
)
async def download_report(
    project_id: ProjectId,
    report_id: ReportId,
    session: SessionDep,
    guest: CurrentGuestSessionDep,
) -> Response:
    project = await guest_access.require_guest_project_access(
        session, project_public_id=project_id, guest=guest
    )
    report = await reports.get_report(session, project=project, report_id=report_id)

    return _pdf_response(report, attachment=True)
