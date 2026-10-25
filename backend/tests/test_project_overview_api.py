"""Project overview's real write and spec-read contracts.

These tests use the real routes over an ASGI transport against the scratch
database.  They cover the authorization boundary, the fields the console sends,
the project aggregate returned after a write, and the spec summary used by the
overview card.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import uuid

import httpx
import pytest
from sqlalchemy import select

from backend.app import create_app
from backend.db import database
from backend.db.models.project import Environment, EnvironmentVariable, Project
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


async def test_guest_can_rename_project_and_read_it_back(fixtures):
    app = create_app()
    _guest, token, project, _spec = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)

    async with app_client(app) as client:
        updated = await client.patch(
            "/api/projects/" + public_id,
            headers={"X-Guest-Session": token},
            json={"name": "  Renamed API  "},
        )
        listed = await client.get("/api/projects", headers={"X-Guest-Session": token})

    assert updated.status_code == 200
    body = updated.json()
    assert body["id"] == public_id
    assert body["name"] == "Renamed API"
    assert any(item["id"] == public_id and item["name"] == "Renamed API" for item in listed.json())


async def test_project_rename_rejects_blank_unauthorized_and_foreign_projects(fixtures):
    app = create_app()
    _guest, token, project, _spec = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)
    _other_guest, other_token = await issue_guest(fixtures)
    other_project = await fixtures.project(_other_guest.id)
    await fixtures.commit()
    other_public_id = await project_public_id(fixtures, other_project)

    async with app_client(app) as client:
        blank = await client.patch(
            "/api/projects/" + public_id,
            headers={"X-Guest-Session": token},
            json={"name": "   "},
        )
        unauth = await client.patch(
            "/api/projects/" + public_id,
            json={"name": "No session"},
        )
        foreign = await client.patch(
            "/api/projects/" + other_public_id,
            headers={"X-Guest-Session": token},
            json={"name": "Not mine"},
        )
        missing = await client.patch(
            "/api/projects/prj_missing_for_update",
            headers={"X-Guest-Session": token},
            json={"name": "Nowhere"},
        )

    assert blank.status_code == 422
    assert unauth.status_code == 401
    assert foreign.status_code == 404
    assert missing.status_code == 404


async def test_environment_update_changes_only_editable_fields(fixtures):
    app = create_app()
    _guest, token, project, _spec = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)
    environment = await fixtures.environment(
        project,
        name="Old env",
        kind="development",
        base_url="http://127.0.0.1:8000",
    )
    variable = await fixtures.environment_variable(environment, key="token", value="keep-me")
    await fixtures.commit()
    environment_public = (
        await fixtures.session.execute(
            select(Environment.public_id).where(Environment.id == environment)
        )
    ).scalar_one()

    async with app_client(app) as client:
        response = await client.patch(
            "/api/projects/" + public_id + "/environments/" + environment_public,
            headers={"X-Guest-Session": token},
            json={
                "name": "Staging env",
                "kind": "staging",
                "baseUrl": "https://staging.example.com",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == public_id
    assert any(
        item["id"] == environment_public
        and item["name"] == "Staging env"
        and item["kind"] == "staging"
        and item["baseUrl"] == "https://staging.example.com"
        for item in body["environments"]
    )

    async with database.AsyncSessionLocal() as session:
        stored = (
            await session.execute(
                select(EnvironmentVariable.value_encrypted).where(EnvironmentVariable.id == variable)
            )
        ).scalar_one()
    assert stored == "keep-me"


async def test_environment_update_rejects_invalid_and_cross_project_input(fixtures):
    app = create_app()
    _guest, token, project, _spec = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)
    await fixtures.environment(project, name="Dev env", public_id="env_overview_dev")
    await fixtures.environment(project, name="Staging env", public_id="env_overview_staging")
    other_project = await fixtures.project(_guest.id)
    await fixtures.environment(
        other_project, name="Other env", public_id="env_overview_other"
    )
    await fixtures.commit()

    base = "/api/projects/" + public_id + "/environments/"
    async with app_client(app) as client:
        invalid_name = await client.patch(
            base + "env_overview_dev",
            headers={"X-Guest-Session": token},
            json={"name": "   ", "kind": "development", "baseUrl": "http://127.0.0.1:8000"},
        )
        invalid_kind = await client.patch(
            base + "env_overview_dev",
            headers={"X-Guest-Session": token},
            json={"name": "Dev", "kind": "qa", "baseUrl": "http://127.0.0.1:8000"},
        )
        invalid_url = await client.patch(
            base + "env_overview_dev",
            headers={"X-Guest-Session": token},
            json={"name": "Dev", "kind": "development", "baseUrl": "not-a-url"},
        )
        duplicate_name = await client.patch(
            base + "env_overview_dev",
            headers={"X-Guest-Session": token},
            json={"name": "Staging env", "kind": "development", "baseUrl": "http://127.0.0.1:8000"},
        )
        cross_project = await client.patch(
            base + "env_overview_other",
            headers={"X-Guest-Session": token},
            json={"name": "Wrong", "kind": "development", "baseUrl": "http://127.0.0.1:8000"},
        )

    assert invalid_name.status_code == 422
    assert invalid_kind.status_code == 422
    assert invalid_url.status_code == 422
    assert duplicate_name.status_code == 409
    assert cross_project.status_code == 404


async def test_spec_read_returns_latest_summary_and_endpoint_count(fixtures):
    app = create_app()
    _guest, token, project, _spec = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)
    now = datetime.now(timezone.utc)
    old_spec = await fixtures.spec(
        project,
        slug="old_spec_" + uuid.uuid4().hex[:8],
        name="Old spec",
        filename="old.json",
        created_at=now - timedelta(days=2),
    )
    await fixtures.endpoint(old_spec, path="/old")
    new_spec = await fixtures.spec(
        project,
        slug="new_spec_" + uuid.uuid4().hex[:8],
        name="Orders API",
        filename="orders-openapi.json",
        created_at=now,
    )
    await fixtures.endpoint(new_spec, path="/orders")
    await fixtures.endpoint(new_spec, path="/orders/{id}", method="GET")
    await fixtures.commit()

    async with app_client(app) as client:
        response = await client.get(
            "/api/projects/" + public_id + "/spec",
            headers={"X-Guest-Session": token},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Orders API"
    assert body["filename"] == "orders-openapi.json"
    assert body["specType"] == "openapi-3"
    assert body["contentFormat"] == "json"
    assert body["endpointCount"] == 2
    assert body["id"].startswith("spec_")
    assert body["createdAt"] is not None
    assert body["updatedAt"] is not None


async def test_spec_read_is_null_for_empty_project_and_rejects_foreign_projects(fixtures):
    app = create_app()
    _guest, token, _project, _spec = await guest_stack(fixtures)
    empty_project = await fixtures.project(_guest.id)
    _other_guest, _other_token = await issue_guest(fixtures)
    other_project = await fixtures.project(_other_guest.id)
    await fixtures.commit()
    empty_public = await project_public_id(fixtures, empty_project)
    other_public = await project_public_id(fixtures, other_project)

    async with app_client(app) as client:
        empty = await client.get(
            "/api/projects/" + empty_public + "/spec",
            headers={"X-Guest-Session": token},
        )
        unauth = await client.get("/api/projects/" + empty_public + "/spec")
        foreign = await client.get(
            "/api/projects/" + other_public + "/spec",
            headers={"X-Guest-Session": token},
        )
        missing = await client.get(
            "/api/projects/prj_missing_spec/spec",
            headers={"X-Guest-Session": token},
        )

    assert empty.status_code == 200
    assert empty.json() is None
    assert unauth.status_code == 401
    assert foreign.status_code == 404
    assert missing.status_code == 404


async def test_account_can_update_and_read_its_own_project(fixtures, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-overview-secret-not-real")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    app = create_app()

    users = [
        User(
            username="overview-a-" + uuid.uuid4().hex[:8],
            email=None,
            email_verified=False,
            password_hash=None,
            status="active",
            provider="github",
            avatar_url=None,
        ),
        User(
            username="overview-b-" + uuid.uuid4().hex[:8],
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
            public_id="overviewacct_" + uuid.uuid4().hex[:10],
            name="Account project " + str(index),
            description=None,
        )
        for index, user in enumerate(users)
    ]
    fixtures.session.add_all(projects)
    for project in projects:
        await fixtures._keep(Project, project)
    await fixtures.commit()

    spec = await fixtures.spec(projects[0].id, name="Account API")
    await fixtures.endpoint(spec)
    await fixtures.commit()

    _session, token = await auth_service.issue_session(
        fixtures.session, users[0], app.state.auth.settings
    )
    await fixtures.session.commit()

    async with app_client(app) as client:
        client.cookies.set("api_session", token)
        renamed = await client.patch(
            "/api/projects/" + projects[0].public_id,
            json={"name": "Account API renamed"},
        )
        spec_read = await client.get("/api/projects/" + projects[0].public_id + "/spec")
        foreign = await client.get("/api/projects/" + projects[1].public_id + "/spec")

    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Account API renamed"
    assert spec_read.status_code == 200
    assert spec_read.json()["name"] == "Account API"
    assert foreign.status_code == 404
