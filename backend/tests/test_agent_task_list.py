"""Project-level agent task listing.

The dashboard's Agent activity card needs the persisted task record, not the
plan list.  These specs drive the real route over an ASGI transport against the
scratch database, so the assertions cover ownership, SQL ordering, the response
contract and the account/Guest Session split rather than only a service helper.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import uuid

import httpx
import pytest
from sqlalchemy import select

from backend.app import create_app
from backend.db.models.project import Project
from backend.db.models.user import GuestSession, User
from backend.services import auth as auth_service
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
    """A real Guest Session row plus the one raw token the client can present."""
    guest, token = await guest_session.issue(fixtures.session)
    await fixtures.session.commit()
    await fixtures._keep(GuestSession, guest)
    return guest, token


async def project_public_id(fixtures, project_id: uuid.UUID) -> str:
    return (
        await fixtures.session.execute(
            select(Project.public_id).where(Project.id == project_id)
        )
    ).scalar_one()


async def guest_stack(fixtures):
    guest, token = await issue_guest(fixtures)
    project = await fixtures.project(guest.id)
    spec = await fixtures.spec(project)
    await fixtures.commit()
    return guest, token, project, spec


async def make_task(fixtures, project, spec, *, status: str, prompt: str, created_at: datetime):
    task = await fixtures.agent_task(
        project,
        spec,
        status=status,
        prompt=prompt,
        created_at=created_at,
        updated_at=created_at,
    )
    return task


def task_path(public_id: str, query: str = "") -> str:
    return "/api/projects/" + public_id + "/agent/tasks" + query


async def test_lists_newest_tasks_and_honours_default_limit(fixtures):
    app = create_app()
    _guest, token, project, spec = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)

    base = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    statuses = ["pending", "analyzing", "completed", "failed"]
    for index, status in enumerate(statuses):
        await make_task(
            fixtures,
            project,
            spec,
            status=status,
            prompt="Task " + status,
            created_at=base + timedelta(minutes=index),
        )
    await fixtures.commit()

    async with app_client(app) as client:
        response = await client.get(
            task_path(public_id), headers={"X-Guest-Session": token}
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    assert [item["prompt"] for item in body] == [
        "Task failed",
        "Task completed",
        "Task analyzing",
    ]
    assert [item["status"] for item in body] == ["failed", "completed", "analyzing"]
    assert set(body[0]) == {
        "id",
        "projectId",
        "prompt",
        "status",
        "createdAt",
        "updatedAt",
    }
    assert body[0]["projectId"] == public_id
    assert datetime.fromisoformat(body[0]["createdAt"].replace("Z", "+00:00")) == base + timedelta(
        minutes=3
    )
    assert datetime.fromisoformat(body[0]["updatedAt"].replace("Z", "+00:00")) == base + timedelta(
        minutes=3
    )


async def test_limit_is_bounded_and_validated(fixtures):
    app = create_app()
    _guest, token, project, spec = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)
    base = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    for index in range(4):
        await make_task(
            fixtures,
            project,
            spec,
            status="completed",
            prompt="Task " + str(index),
            created_at=base + timedelta(minutes=index),
        )
    await fixtures.commit()

    async with app_client(app) as client:
        limited = await client.get(
            task_path(public_id, "?limit=1"), headers={"X-Guest-Session": token}
        )
        too_small = await client.get(
            task_path(public_id, "?limit=0"), headers={"X-Guest-Session": token}
        )
        too_large = await client.get(
            task_path(public_id, "?limit=21"), headers={"X-Guest-Session": token}
        )

    assert limited.status_code == 200
    assert [item["prompt"] for item in limited.json()] == ["Task 3"]
    assert too_small.status_code == 422
    assert too_large.status_code == 422


async def test_equal_timestamps_have_a_stable_uuid_tiebreaker(fixtures):
    app = create_app()
    _guest, token, project, spec = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)
    created_at = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    first = await make_task(
        fixtures,
        project,
        spec,
        status="pending",
        prompt="First",
        created_at=created_at,
    )
    second = await make_task(
        fixtures,
        project,
        spec,
        status="pending",
        prompt="Second",
        created_at=created_at,
    )
    await fixtures.commit()

    async with app_client(app) as client:
        response = await client.get(
            task_path(public_id), headers={"X-Guest-Session": token}
        )

    assert response.status_code == 200
    expected = sorted([str(first), str(second)], reverse=True)
    assert [item["id"] for item in response.json()] == expected


async def test_empty_project_returns_an_empty_array(fixtures):
    app = create_app()
    _guest, token, project, _spec = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)

    async with app_client(app) as client:
        response = await client.get(
            task_path(public_id), headers={"X-Guest-Session": token}
        )

    assert response.status_code == 200
    assert response.json() == []


async def test_missing_foreign_and_unauthenticated_requests_are_rejected(fixtures):
    app = create_app()
    _guest, token, project, _spec = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)

    other_guest, _other_token = await issue_guest(fixtures)
    other_project = await fixtures.project(other_guest.id)
    await fixtures.commit()
    other_public_id = await project_public_id(fixtures, other_project)

    async with app_client(app) as client:
        unauthenticated = await client.get(task_path(public_id))
        missing = await client.get(
            task_path("prj_does_not_exist"), headers={"X-Guest-Session": token}
        )
        foreign = await client.get(
            task_path(other_public_id), headers={"X-Guest-Session": token}
        )

    assert unauthenticated.status_code == 401
    assert missing.status_code == 404
    assert foreign.status_code == 404


async def test_account_session_can_read_own_tasks_but_not_another_account(fixtures, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-task-list-secret-not-real")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    app = create_app()

    users = [
        User(
            username="task-list-a-" + uuid.uuid4().hex[:8],
            email=None,
            email_verified=False,
            password_hash=None,
            status="active",
            provider="github",
            avatar_url=None,
        ),
        User(
            username="task-list-b-" + uuid.uuid4().hex[:8],
            email=None,
            email_verified=False,
            password_hash=None,
            status="active",
            provider="github",
            avatar_url=None,
        ),
    ]
    fixtures.session.add_all(users)
    await fixtures.session.commit()
    for user in users:
        await fixtures._keep(User, user)
        await auth_service.internal_guest_for_user(fixtures.session, user)

    projects = [
        Project(
            user_id=user.id,
            guest_session_id=None,
            public_id="tasklist_" + uuid.uuid4().hex[:10],
            name="Task list account project " + str(index),
            description=None,
        )
        for index, user in enumerate(users)
    ]
    fixtures.session.add_all(projects)
    for project in projects:
        await fixtures._keep(Project, project)
    await fixtures.session.commit()

    spec_a = await fixtures.spec(projects[0].id)
    await make_task(
        fixtures,
        projects[0].id,
        spec_a,
        status="completed",
        prompt="Account task",
        created_at=datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc),
    )
    await fixtures.commit()

    _session, token = await auth_service.issue_session(
        fixtures.session, users[0], app.state.auth.settings
    )
    await fixtures.session.commit()

    async with app_client(app) as client:
        client.cookies.set("api_session", token)
        own = await client.get(task_path(projects[0].public_id))
        foreign = await client.get(task_path(projects[1].public_id))

    assert own.status_code == 200
    assert [item["prompt"] for item in own.json()] == ["Account task"]
    assert foreign.status_code == 404
