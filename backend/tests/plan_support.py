"""Test helpers for the server-side approval flow.

Run-create tests used to submit a body whose plan.status said approved and let
the service materialise the plan from that body. That path is gone: a run now
requires a stored, approved, fingerprinted plan. These helpers persist the same
payload the test is about and issue the approval receipt, so the test still
exercises the product code rather than fabricating a row by hand.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models.agent import TestPlan
from backend.db.models.project import Project
from backend.schemas.run import RunCreateRequest
from backend.services import plan_hash, runs
from backend.services.spec_identity import derive_spec_identity, probe_document

__all__ = [
    "approve_plan_by_id",
    "approve_plan_row",
    "persist_approved_plan",
    "persist_plan",
]


async def _project_public_id(session: AsyncSession, project_id: uuid.UUID) -> str:
    return (
        await session.execute(
            select(Project.public_id).where(Project.id == project_id)
        )
    ).scalar_one()


async def persist_plan(
    session: AsyncSession, *, project_id: uuid.UUID, payload: RunCreateRequest
) -> TestPlan:
    """Materialise the payload plan as a draft row, exactly as the agent would."""
    facts = probe_document(payload.spec_document)
    identity = derive_spec_identity(
        spec_document=payload.spec_document,
        spec_id=payload.spec_id,
        facts=facts,
    )
    spec = await runs._get_or_create_spec(
        session,
        project_id=project_id,
        spec_document=payload.spec_document,
        facts=facts,
        identity=identity,
    )
    materialization = await runs._create_plan_tree(
        session, project_id=project_id, spec_id=spec.id, plan=payload.plan
    )
    row = await session.get(TestPlan, materialization.plan_id)
    assert row is not None
    return row


def _apply_actor(row: TestPlan, project: Project) -> None:
    if project.user_id is not None:
        row.approved_by_user_id = project.user_id
        row.approved_by_guest_session_id = None
    else:
        row.approved_by_guest_session_id = project.guest_session_id
        row.approved_by_user_id = None


async def approve_plan_row(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    row: TestPlan,
    project_public_id: str,
) -> TestPlan:
    """Issue the receipt for a stored row (the service equivalent under test)."""
    stored = await plan_hash.load_stored_plan(
        session, plan=row, project_public_id=project_public_id
    )
    project = await session.get(Project, project_id)
    assert project is not None
    row.status = "approved"
    row.approved_at = datetime.now(timezone.utc)
    row.content_hash = stored.content_hash
    row.rejected_at = None
    row.rejection_reason = None
    _apply_actor(row, project)
    await session.flush()
    return row


async def approve_plan_by_id(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    plan_row_id: uuid.UUID,
    project_public_id: str | None = None,
) -> TestPlan:
    row = await session.get(TestPlan, plan_row_id)
    assert row is not None
    public_id = project_public_id or await _project_public_id(session, project_id)
    return await approve_plan_row(
        session, project_id=project_id, row=row, project_public_id=public_id
    )


async def persist_approved_plan(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    payload: RunCreateRequest,
    project_public_id: str | None = None,
) -> TestPlan:
    """Persist the payload plan if needed, then approve it.

    Idempotent per (project, public_id): a second call for a plan already in
    the database reuses the stored tree and re-issues the receipt for it,
    which is what a repeated create in a race test needs.
    """
    public_id = project_public_id or await _project_public_id(session, project_id)

    existing = (
        await session.execute(
            select(TestPlan).where(
                TestPlan.project_id == project_id,
                TestPlan.public_id == payload.plan.id,
                TestPlan.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        existing = await persist_plan(session, project_id=project_id, payload=payload)

    return await approve_plan_row(
        session, project_id=project_id, row=existing, project_public_id=public_id
    )
