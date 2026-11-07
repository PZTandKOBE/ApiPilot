"""Server-side approval: transitions, permissions, the receipt and its checks.

These tests exercise services.agent.approve_plan / reject_plan and the two
HTTP routes. The database constraints are asserted directly as well, because
the receipt has to hold even when a future writer forgets the service.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from backend.api.errors import AppError
from backend.app import create_app
from backend.db.models.agent import TestPlan
from backend.db.models.project import ApiSpec, Project
from backend.db.models.user import GuestSession, User
from backend.schemas.agent import PlanRejectRequest
from backend.services import agent, guest_session, runs
from backend.services.spec_identity import spec_id_for

from tests.plan_support import approve_plan_row
from tests.test_plan_hash import PLAN_ID, _payload, _seed

pytestmark = pytest.mark.anyio


async def _project_and_guest(fixtures, stack):
    project = await fixtures.session.get(Project, stack["project"])
    guest = await fixtures.session.get(GuestSession, stack["guest"])
    assert project is not None and guest is not None
    return project, guest


async def test_approve_writes_a_complete_receipt(fixtures, stack) -> None:
    rows = await _seed(fixtures, stack)
    project, guest = await _project_and_guest(fixtures, stack)

    response = await agent.approve_plan(
        fixtures.session, project=project, plan_id=PLAN_ID, guest=guest
    )
    await fixtures.session.commit()

    assert response.status == "approved"
    assert response.approved_by == "guest"
    assert response.approved_at is not None

    stored = await fixtures.session.get(TestPlan, rows.plan.id)
    assert stored is not None
    assert stored.status == "approved"
    assert stored.approved_at is not None
    assert stored.content_hash is not None and len(stored.content_hash) == 64
    assert stored.approved_by_guest_session_id == stack["guest"]
    assert stored.approved_by_user_id is None


async def test_approve_is_idempotent_while_content_is_unchanged(
    fixtures, stack
) -> None:
    await _seed(fixtures, stack)
    project, guest = await _project_and_guest(fixtures, stack)

    first = await agent.approve_plan(
        fixtures.session, project=project, plan_id=PLAN_ID, guest=guest
    )
    await fixtures.session.commit()
    first_at = first.approved_at

    second = await agent.approve_plan(
        fixtures.session, project=project, plan_id=PLAN_ID, guest=guest
    )
    await fixtures.session.commit()

    assert second.approved_at == first_at, "a retried approve rewrote the review moment"
    assert second.status == "approved"


async def test_reject_clears_the_approval_credential(fixtures, stack) -> None:
    rows = await _seed(fixtures, stack)
    project, guest = await _project_and_guest(fixtures, stack)
    await agent.approve_plan(
        fixtures.session, project=project, plan_id=PLAN_ID, guest=guest
    )
    await fixtures.session.commit()

    response = await agent.reject_plan(
        fixtures.session,
        project=project,
        plan_id=PLAN_ID,
        guest=guest,
        reason="  not ready  ",
    )
    await fixtures.session.commit()

    assert response.status == "rejected"
    assert response.approved_by is None
    stored = await fixtures.session.get(TestPlan, rows.plan.id)
    assert stored is not None
    assert stored.status == "rejected"
    assert stored.rejection_reason == "not ready"
    assert stored.approved_at is None
    assert stored.content_hash is None
    assert stored.approved_by_guest_session_id is None
    assert stored.approved_by_user_id is None


async def test_reject_is_idempotent_and_keeps_the_first_sentence(
    fixtures, stack
) -> None:
    rows = await _seed(fixtures, stack)
    project, guest = await _project_and_guest(fixtures, stack)

    await agent.reject_plan(
        fixtures.session, project=project, plan_id=PLAN_ID, guest=guest, reason="first"
    )
    await fixtures.session.commit()
    await agent.reject_plan(
        fixtures.session, project=project, plan_id=PLAN_ID, guest=guest, reason="second"
    )
    await fixtures.session.commit()

    stored = await fixtures.session.get(TestPlan, rows.plan.id)
    assert stored is not None
    assert stored.status == "rejected"
    assert stored.rejection_reason == "first"


async def test_a_rejected_plan_can_be_approved_again(fixtures, stack) -> None:
    rows = await _seed(fixtures, stack)
    project, guest = await _project_and_guest(fixtures, stack)
    await agent.reject_plan(
        fixtures.session, project=project, plan_id=PLAN_ID, guest=guest, reason="retry"
    )
    await fixtures.session.commit()

    response = await agent.approve_plan(
        fixtures.session, project=project, plan_id=PLAN_ID, guest=guest
    )
    await fixtures.session.commit()

    assert response.status == "approved"
    stored = await fixtures.session.get(TestPlan, rows.plan.id)
    assert stored is not None
    assert stored.rejected_at is None
    assert stored.rejection_reason is None


async def test_unknown_and_deleted_plans_are_not_found(fixtures, stack) -> None:
    rows = await _seed(fixtures, stack)
    project, guest = await _project_and_guest(fixtures, stack)

    with pytest.raises(Exception) as missing:
        await agent.approve_plan(
            fixtures.session, project=project, plan_id="plan_nope", guest=guest
        )
    assert getattr(missing.value, "status_code", None) == 404

    await fixtures.session.execute(
        update(TestPlan)
        .where(TestPlan.id == rows.plan.id)
        .values(deleted_at=datetime.now(timezone.utc))
    )
    await fixtures.session.commit()
    with pytest.raises(Exception) as deleted:
        await agent.approve_plan(
            fixtures.session, project=project, plan_id=PLAN_ID, guest=guest
        )
    assert getattr(deleted.value, "status_code", None) == 404


async def test_an_account_approval_records_the_user_id(fixtures) -> None:
    """The account branch stores approved_by_user_id and never the guest id."""
    user = User(username="c20_user_" + uuid.uuid4().hex[:10], provider="github")
    fixtures.session.add(user)
    await fixtures.session.flush()
    guest = GuestSession(
        user_id=user.id,
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        expires_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    fixtures.session.add(guest)
    await fixtures.session.flush()

    project = Project(
        user_id=user.id,
        public_id="c20prj_" + uuid.uuid4().hex[:8],
        name="C20 account project",
    )
    fixtures.session.add(project)
    await fixtures.session.flush()
    spec = ApiSpec(
        project_id=project.id,
        name="C20 spec",
        slug="c20spec_" + uuid.uuid4().hex[:8],
        spec_type="openapi-3",
        content_format="json",
        content="{}",
    )
    fixtures.session.add(spec)
    await fixtures.session.flush()

    payload = _payload(project_id=project.public_id, spec_id=spec_id_for(spec.slug))
    materialization = await runs._create_plan_tree(
        fixtures.session, project_id=project.id, spec_id=spec.id, plan=payload
    )
    row = await fixtures.session.get(TestPlan, materialization.plan_id)
    assert row is not None

    response = await agent.approve_plan(
        fixtures.session, project=project, plan_id=PLAN_ID, guest=guest
    )
    await fixtures.session.commit()

    assert response.approved_by == "account"
    stored = await fixtures.session.get(TestPlan, row.id)
    assert stored is not None
    assert stored.approved_by_user_id == user.id
    assert stored.approved_by_guest_session_id is None


async def test_the_database_refuses_an_approved_row_without_a_receipt(
    fixtures, stack
) -> None:
    rows = await _seed(fixtures, stack)

    with pytest.raises(IntegrityError):
        await fixtures.session.execute(
            update(TestPlan).where(TestPlan.id == rows.plan.id).values(status="approved")
        )
        await fixtures.session.flush()
    await fixtures.session.rollback()


async def test_the_database_refuses_two_actors(fixtures, stack) -> None:
    rows = await _seed(fixtures, stack)
    project, guest = await _project_and_guest(fixtures, stack)
    await approve_plan_row(
        fixtures.session,
        project_id=stack["project"],
        row=rows.plan,
        project_public_id=project.public_id,
    )
    await fixtures.session.flush()

    user = User(username="c20_dual_" + uuid.uuid4().hex[:10], provider="github")
    fixtures.session.add(user)
    await fixtures.session.flush()
    with pytest.raises(IntegrityError):
        await fixtures.session.execute(
            update(TestPlan)
            .where(TestPlan.id == rows.plan.id)
            .values(approved_by_user_id=user.id)
        )
        await fixtures.session.flush()
    await fixtures.session.rollback()


def test_reject_request_requires_a_non_blank_reason() -> None:
    with pytest.raises(ValidationError):
        PlanRejectRequest.model_validate({"reason": "   "})
    with pytest.raises(ValidationError):
        PlanRejectRequest.model_validate({"reason": ""})

    accepted = PlanRejectRequest.model_validate({"reason": "  use v2  "})
    assert accepted.reason == "use v2"


@asynccontextmanager
async def _client():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client


async def _guest_stack(fixtures):
    guest, token = await guest_session.issue(fixtures.session)
    await fixtures.session.commit()
    project = await fixtures.project(guest.id)
    spec = await fixtures.spec(project)
    await fixtures.session.commit()
    public_id = (
        await fixtures.session.execute(
            select(Project.public_id).where(Project.id == project)
        )
    ).scalar_one()
    slug = (
        await fixtures.session.execute(select(ApiSpec.slug).where(ApiSpec.id == spec))
    ).scalar_one()
    payload = _payload(project_id=public_id, spec_id=spec_id_for(slug))
    await runs._create_plan_tree(
        fixtures.session, project_id=project, spec_id=spec, plan=payload
    )
    await fixtures.session.commit()
    return token, public_id


async def test_approve_and_reject_over_http(fixtures) -> None:
    token, project_public_id = await _guest_stack(fixtures)
    headers = {"X-Guest-Session": token}

    async with _client() as client:
        approved = await client.post(
            f"/api/projects/{project_public_id}/plans/{PLAN_ID}/approve",
            headers=headers,
        )
        assert approved.status_code == 200, approved.text
        body = approved.json()
        assert body["status"] == "approved"
        assert body["approvedBy"] == "guest"

        rejected = await client.post(
            f"/api/projects/{project_public_id}/plans/{PLAN_ID}/reject",
            headers=headers,
            json={"reason": "needs work"},
        )
        assert rejected.status_code == 200, rejected.text
        rejected_body = rejected.json()
        assert rejected_body["status"] == "rejected"
        assert rejected_body["rejectionReason"] == "needs work"

        blank = await client.post(
            f"/api/projects/{project_public_id}/plans/{PLAN_ID}/reject",
            headers=headers,
            json={"reason": "   "},
        )
        assert blank.status_code == 422, blank.text


async def test_http_approval_refuses_a_foreign_guest(fixtures) -> None:
    _token, project_public_id = await _guest_stack(fixtures)

    _other_guest, other_token = await guest_session.issue(fixtures.session)
    await fixtures.session.commit()

    async with _client() as client:
        response = await client.post(
            f"/api/projects/{project_public_id}/plans/{PLAN_ID}/approve",
            headers={"X-Guest-Session": other_token},
        )
    assert response.status_code == 404, response.text


async def test_reapproving_changed_content_issues_a_new_receipt(
    fixtures, stack,
) -> None:
    """An explicit second approve binds the receipt to the content as it is now."""
    from backend.db.models.agent import TestStep
    from sqlalchemy import update

    rows = await _seed(fixtures, stack)
    project, guest = await _project_and_guest(fixtures, stack)
    first = await agent.approve_plan(
        fixtures.session, project=project, plan_id=PLAN_ID, guest=guest
    )
    await fixtures.session.commit()
    first_hash = (await fixtures.session.get(TestPlan, rows.plan.id)).content_hash

    step = (
        await fixtures.session.execute(
            select(TestStep).where(TestStep.id == rows.request_step.id)
        )
    ).scalar_one()
    config = dict(step.config or {})
    config["path"] = "/changed/after/approval"
    await fixtures.session.execute(
        update(TestStep).where(TestStep.id == step.id).values(config=config)
    )
    await fixtures.session.flush()

    second = await agent.approve_plan(
        fixtures.session, project=project, plan_id=PLAN_ID, guest=guest
    )
    await fixtures.session.commit()

    assert second.status == "approved"
    updated = await fixtures.session.get(TestPlan, rows.plan.id)
    assert updated is not None
    assert updated.content_hash != first_hash
    assert updated.approved_at is not None


# --------------------------------------------------------------------------- #
# Concurrency: the row lock serialises reviewers
# --------------------------------------------------------------------------- #


async def _approve_in_session(project_id, guest_id) -> object:
    from backend.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        guest = await session.get(GuestSession, guest_id)
        assert project is not None and guest is not None
        response = await agent.approve_plan(
            session, project=project, plan_id=PLAN_ID, guest=guest
        )
        await session.commit()
        return response


async def _reject_in_session(project_id, guest_id) -> object:
    from backend.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        guest = await session.get(GuestSession, guest_id)
        assert project is not None and guest is not None
        response = await agent.reject_plan(
            session, project=project, plan_id=PLAN_ID, guest=guest, reason="concurrent"
        )
        await session.commit()
        return response


async def test_two_concurrent_approves_serialise_on_the_row(fixtures, stack) -> None:
    """Both requests succeed; the second sees the first receipt and is idempotent."""
    import asyncio

    await _seed(fixtures, stack)
    await fixtures.commit()

    first, second = await asyncio.gather(
        _approve_in_session(stack["project"], stack["guest"]),
        _approve_in_session(stack["project"], stack["guest"]),
    )

    assert first.status == "approved"
    assert second.status == "approved"
    assert first.approved_at == second.approved_at, (
        "the second approve rewrote the receipt instead of observing it"
    )


async def test_approve_and_reject_arriving_together_leave_one_consistent_state(
    fixtures, stack,
) -> None:
    """The row lock orders the two transitions instead of interleaving them."""
    import asyncio

    from backend.db.database import AsyncSessionLocal

    rows = await _seed(fixtures, stack)
    await fixtures.commit()

    approved, rejected = await asyncio.gather(
        _approve_in_session(stack["project"], stack["guest"]),
        _reject_in_session(stack["project"], stack["guest"]),
    )

    assert approved.status == "approved"
    assert rejected.status == "rejected"

    async with AsyncSessionLocal() as fresh:
        stored = await fresh.get(TestPlan, rows.plan.id)
        assert stored is not None
        if stored.status == "approved":
            assert stored.content_hash is not None
            assert stored.approved_by_guest_session_id == stack["guest"]
            assert stored.rejected_at is None
        else:
            assert stored.status == "rejected"
            assert stored.content_hash is None
            assert stored.approved_by_guest_session_id is None


# --------------------------------------------------------------------------- #
# Structure gate: an empty tree cannot receive an approval receipt
# --------------------------------------------------------------------------- #


async def _persist_payload(fixtures, stack, plan):
    from backend.services.spec_identity import spec_id_for

    project_public_id = (
        await fixtures.session.execute(
            select(Project.public_id).where(Project.id == stack["project"])
        )
    ).scalar_one()
    slug = (
        await fixtures.session.execute(
            select(ApiSpec.slug).where(ApiSpec.id == stack["spec"])
        )
    ).scalar_one()
    plan = plan.model_copy(
        update={"project_id": project_public_id, "spec_id": spec_id_for(slug)}
    )
    materialization = await runs._create_plan_tree(
        fixtures.session,
        project_id=stack["project"],
        spec_id=stack["spec"],
        plan=plan,
    )
    row = await fixtures.session.get(TestPlan, materialization.plan_id)
    assert row is not None
    return row


async def _approve_and_assert_invalid(fixtures, stack, plan) -> None:
    row = await _persist_payload(fixtures, stack, plan)
    row_id = row.id
    await fixtures.session.commit()
    project, guest = await _project_and_guest(fixtures, stack)
    with pytest.raises(AppError) as caught:
        await agent.approve_plan(
            fixtures.session, project=project, plan_id=plan.id, guest=guest
        )
    assert caught.value.code == "plan-invalid"
    await fixtures.session.rollback()

    stored = (
        await fixtures.session.execute(select(TestPlan).where(TestPlan.id == row_id))
    ).scalar_one()
    assert stored.status == "draft"
    assert stored.approved_at is None
    assert stored.content_hash is None
    assert stored.approved_by_guest_session_id is None
    assert stored.approved_by_user_id is None


async def _payload_for(fixtures, stack):
    from backend.services.spec_identity import spec_id_for

    project_public_id = (
        await fixtures.session.execute(
            select(Project.public_id).where(Project.id == stack["project"])
        )
    ).scalar_one()
    slug = (
        await fixtures.session.execute(
            select(ApiSpec.slug).where(ApiSpec.id == stack["spec"])
        )
    ).scalar_one()
    import uuid

    return _payload(project_id=project_public_id, spec_id=spec_id_for(slug)).model_copy(
        update={"id": "plan_approval_struct_" + uuid.uuid4().hex[:8]}
    )


def _with_empty_scenarios(plan):
    return plan.model_copy(update={"scenarios": []})


def _with_empty_scenario(plan):
    scenarios = [scenario.model_copy(deep=True) for scenario in plan.scenarios]
    scenarios[0].steps = []
    scenarios[0].assertions = []
    return plan.model_copy(update={"scenarios": scenarios})


def _with_assert_only_scenario(plan):
    scenarios = [scenario.model_copy(deep=True) for scenario in plan.scenarios]
    assert_step = scenarios[0].steps[2].model_copy(deep=True)
    assert_step.index = 0
    scenarios[0].steps = [assert_step]
    scenarios[0].assertions = [
        assertion.model_copy(update={"step_id": assert_step.id})
        for assertion in scenarios[0].assertions
    ]
    return plan.model_copy(update={"scenarios": scenarios})


async def test_an_empty_plan_cannot_be_approved(fixtures, stack) -> None:
    await _approve_and_assert_invalid(
        fixtures, stack, _with_empty_scenarios(await _payload_for(fixtures, stack))
    )


async def test_a_plan_with_an_empty_scenario_cannot_be_approved(fixtures, stack) -> None:
    await _approve_and_assert_invalid(
        fixtures, stack, _with_empty_scenario(await _payload_for(fixtures, stack))
    )


async def test_a_scenario_without_a_request_cannot_be_approved(fixtures, stack) -> None:
    await _approve_and_assert_invalid(
        fixtures, stack, _with_assert_only_scenario(await _payload_for(fixtures, stack))
    )


async def test_a_legacy_path_only_extract_can_still_be_approved(fixtures, stack) -> None:
    plan = await _payload_for(fixtures, stack)
    scenario = plan.scenarios[0].model_copy(deep=True)
    steps = [step.model_copy(deep=True) for step in scenario.steps]
    steps[1].source_step_id = None
    plan = plan.model_copy(
        update={"scenarios": [scenario.model_copy(update={"steps": steps})]}
    )
    _row = await _persist_payload(fixtures, stack, plan)
    project, guest = await _project_and_guest(fixtures, stack)

    response = await agent.approve_plan(
        fixtures.session, project=project, plan_id=plan.id, guest=guest
    )
    await fixtures.session.commit()

    assert response.status == "approved"


async def test_an_already_approved_invalid_plan_cannot_refresh_its_receipt(
    fixtures, stack
) -> None:
    plan = _with_empty_scenario(await _payload_for(fixtures, stack))
    row = await _persist_payload(fixtures, stack, plan)
    row_id = row.id
    project = await fixtures.session.get(Project, stack["project"])
    assert project is not None
    await approve_plan_row(
        fixtures.session,
        project_id=stack["project"],
        row=row,
        project_public_id=await fixtures.session.scalar(
            select(Project.public_id).where(Project.id == stack["project"])
        ),
    )
    before = (
        row.status,
        row.approved_at,
        row.content_hash,
        row.approved_by_guest_session_id,
        row.approved_by_user_id,
    )
    assert before[3] is not None or before[4] is not None
    await fixtures.session.commit()

    project, guest = await _project_and_guest(fixtures, stack)
    with pytest.raises(AppError) as caught:
        await agent.approve_plan(
            fixtures.session, project=project, plan_id=plan.id, guest=guest
        )
    assert caught.value.code == "plan-invalid"
    await fixtures.session.rollback()

    after_row = await fixtures.session.get(TestPlan, row_id)
    assert after_row is not None
    after = (
        after_row.status,
        after_row.approved_at,
        after_row.content_hash,
        after_row.approved_by_guest_session_id,
        after_row.approved_by_user_id,
    )
    assert after == before
    assert after_row.status == "approved"
    assert after_row.approved_at is not None
    assert after_row.content_hash is not None


async def test_an_invalid_assertion_binding_cannot_be_approved(
    fixtures, stack,
) -> None:
    """A stored assertion bound to a request step is structurally invalid.

    A binding naming a non-existent step cannot be stored: test_assertions.step_id
    is a foreign key, and _create_plan_tree normalizes an unresolvable payload
    target to NULL (the legacy checkpoint fallback).  The request-step binding is
    the invalid form that can exist in the database and must be rejected.
    """
    plan = await _payload_for(fixtures, stack)
    plan.scenarios[0].assertions[0].step_id = plan.scenarios[0].steps[0].id
    await _approve_and_assert_invalid(fixtures, stack, plan)
