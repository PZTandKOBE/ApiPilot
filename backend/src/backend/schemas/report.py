"""Report metadata response shapes."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from backend.schemas.base import Schema
from backend.schemas.run import RunStatus

__all__ = ["RunReportResponse"]


class RunReportResponse(Schema):
    """One saved PDF report, without its bytes."""

    id: str = Field(description="run_reports.id, used as the only file address.")
    project_id: str
    run_id: str
    name: str
    filename: str
    content_type: str
    byte_size: int
    sha256: str
    generated_at: datetime = Field(description="run_reports.created_at.")
    run_status: RunStatus = Field(description="Status of the source run, read from its row.")
