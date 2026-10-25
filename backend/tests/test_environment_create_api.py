"""Environment creation over the real project route.

The database already models a project with many environments; these specs prove
the new route keeps that relationship intact: a created row belongs to the
project, starts without variables, and never replaces the existing default.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
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
    environment = await fixtures.environment(
        project,
        name="Development",
        kind="development",
        base_url="http://127.0.0.1:8000",
        public_id="env_create_default",
        is_default=True,
    )
    await fixtures.commit()
    return guest, token, project, environment


async def environment_rows(fixtures, project_id: uuid.UUID):
    return (
        await fixtures.session.execute(
            select(Environment).where(Environment.project_id == project_id)
        )
    ).scalars().all()


async def test_creates_all_supported_kinds_and_keeps_the_default(fixtures):
    app = create_app()
    _guest, token, project, default_environment = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)

    async with app_client(app) as client:
        for index, kind in enumerate(["development", "testing", "staging", "production"]):
            response = await client.post(
                "/api/projects/" + public_id + "/environments",
                headers={"X-Guest-Session": token},
                json={
                    "name": "Environment " + str(index),
                    "kind": kind,
                    "baseUrl": "https://" + kind + ".example.com",
                },
            )
            assert response.status_code == 201
            created = next(
                item
                for item in response.json()["environments"]
                if item["name"] == "Environment " + str(index)
            )
            assert created["id"].startswith("env_")
            assert created["name"] == "Environment " + str(index)
            assert created["kind"] == kind
            assert created["baseUrl"] == "https://" + kind + ".example.com"

    rows = await environment_rows(fixtures, project)
    assert len(rows) == 5
    assert [row.kind for row in rows].count("testing") == 1
    assert {row.kind for row in rows} == {"development", "testing", "staging", "production"}
    defaults = [row for row in rows if row.is_default]
    assert len(defaults) == 1
    assert defaults[0].id == default_environment
    new_rows = [row for row in rows if row.id != default_environment]
    assert all(row.is_default is False for row in new_rows)
    assert all(row.public_id.startswith("env_") for row in new_rows)


async def test_same_type_can_have_multiple_independent_environments(fixtures):
    app = create_app()
    _guest, token, project, _default = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)

    async with app_client(app) as client:
        first = await client.post(
            "/api/projects/" + public_id + "/environments",
            headers={"X-Guest-Session": token},
            json={"name": "Test EU", "kind": "testing", "baseUrl": "https://eu.test.example.com"},
        )
        second = await client.post(
            "/api/projects/" + public_id + "/environments",
            headers={"X-Guest-Session": token},
            json={"name": "Test US", "kind": "testing", "baseUrl": "https://us.test.example.com"},
        )

    assert first.status_code == 201
    assert second.status_code == 201
    first_row = next(item for item in first.json()["environments"] if item["name"] == "Test EU")
    second_row = next(item for item in second.json()["environments"] if item["name"] == "Test US")
    assert first_row["id"] != second_row["id"]
    assert first_row["kind"] == second_row["kind"] == "testing"
    assert first_row["baseUrl"] != second_row["baseUrl"]


async def test_new_environment_has_no_copied_variables(fixtures):
    app = create_app()
    _guest, token, project, default_environment = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)
    await fixtures.environment_variable(default_environment, key="secret", value="keep-me")
    await fixtures.commit()

    async with app_client(app) as client:
        response = await client.post(
            "/api/projects/" + public_id + "/environments",
            headers={"X-Guest-Session": token},
            json={"name": "Empty variables", "kind": "testing", "baseUrl": "https://test.example.com"},
        )

    assert response.status_code == 201
    new_public_id = next(
        item["id"] for item in response.json()["environments"] if item["name"] == "Empty variables"
    )

    async with database.AsyncSessionLocal() as session:
        new_environment = (
            await session.execute(select(Environment).where(Environment.public_id == new_public_id))
        ).scalar_one()
        new_variables = (
            await session.execute(
                select(EnvironmentVariable).where(
                    EnvironmentVariable.environment_id == new_environment.id
                )
            )
        ).scalars().all()
        old_variable = (
            await session.execute(
                select(EnvironmentVariable).where(
                    EnvironmentVariable.environment_id == default_environment,
                    EnvironmentVariable.key == "secret",
                )
            )
        ).scalar_one()

    assert new_variables == []
    assert old_variable.value_encrypted == "keep-me"


async def test_existing_environment_can_be_edited_into_testing(fixtures):
    app = create_app()
    _guest, token, project, default_environment = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)

    async with app_client(app) as client:
        response = await client.patch(
            "/api/projects/" + public_id + "/environments/env_create_default",
            headers={"X-Guest-Session": token},
            json={
                "name": "Development",
                "kind": "testing",
                "baseUrl": "http://127.0.0.1:8000",
            },
        )

    assert response.status_code == 200
    edited = next(
        item for item in response.json()["environments"] if item["id"] == "env_create_default"
    )
    assert edited["kind"] == "testing"

    async with database.AsyncSessionLocal() as session:
        stored = (
            await session.execute(
                select(Environment).where(Environment.id == default_environment)
            )
        ).scalar_one()
        assert stored.kind == "testing"
        assert stored.is_default is True


async def test_validation_duplicate_and_authorization_boundaries(fixtures):
    app = create_app()
    _guest, token, project, _default = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)
    other_guest, _other_token = await issue_guest(fixtures)
    other_project = await fixtures.project(other_guest.id)
    await fixtures.commit()
    other_public_id = await project_public_id(fixtures, other_project)

    async with app_client(app) as client:
        blank = await client.post(
            "/api/projects/" + public_id + "/environments",
            headers={"X-Guest-Session": token},
            json={"name": "   ", "kind": "testing", "baseUrl": "https://test.example.com"},
        )
        bad_kind = await client.post(
            "/api/projects/" + public_id + "/environments",
            headers={"X-Guest-Session": token},
            json={"name": "QA", "kind": "qa", "baseUrl": "https://test.example.com"},
        )
        bad_url = await client.post(
            "/api/projects/" + public_id + "/environments",
            headers={"X-Guest-Session": token},
            json={"name": "QA", "kind": "testing", "baseUrl": "not-a-url"},
        )
        duplicate = await client.post(
            "/api/projects/" + public_id + "/environments",
            headers={"X-Guest-Session": token},
            json={"name": "Development", "kind": "testing", "baseUrl": "https://test.example.com"},
        )
        unauth = await client.post(
            "/api/projects/" + public_id + "/environments",
            json={"name": "No session", "kind": "testing", "baseUrl": "https://test.example.com"},
        )
        foreign = await client.post(
            "/api/projects/" + other_public_id + "/environments",
            headers={"X-Guest-Session": token},
            json={"name": "Wrong project", "kind": "testing", "baseUrl": "https://test.example.com"},
        )

    assert blank.status_code == 422
    assert bad_kind.status_code == 422
    assert bad_url.status_code == 422
    assert duplicate.status_code == 409
    assert unauth.status_code == 401
    assert foreign.status_code == 404


async def test_same_name_is_allowed_in_a_different_project(fixtures):
    app = create_app()
    _guest, token, project, _default = await guest_stack(fixtures)
    public_id = await project_public_id(fixtures, project)
    second_project = await fixtures.project(_guest.id)
    await fixtures.commit()
    second_public_id = await project_public_id(fixtures, second_project)

    async with app_client(app) as client:
        first = await client.post(
            "/api/projects/" + public_id + "/environments",
            headers={"X-Guest-Session": token},
            json={"name": "Shared name", "kind": "testing", "baseUrl": "https://a.example.com"},
        )
        second = await client.post(
            "/api/projects/" + second_public_id + "/environments",
            headers={"X-Guest-Session": token},
            json={"name": "Shared name", "kind": "testing", "baseUrl": "https://b.example.com"},
        )

    assert first.status_code == 201
    assert second.status_code == 201


async def test_account_can_create_environment_in_its_own_project(fixtures, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-env-create-secret-not-real")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    app = create_app()

    user = User(
        username="env-create-" + uuid.uuid4().hex[:8],
        email=None,
        email_verified=False,
        password_hash=None,
        status="active",
        provider="github",
        avatar_url=None,
    )
    fixtures.session.add(user)
    await fixtures.session.commit()
    await fixtures._keep(User, user)
    await auth_service.internal_guest_for_user(fixtures.session, user)
    project = Project(
        user_id=user.id,
        guest_session_id=None,
        public_id="envcreate_" + uuid.uuid4().hex[:10],
        name="Account env project",
        description=None,
    )
    fixtures.session.add(project)
    await fixtures._keep(Project, project)
    await fixtures.session.commit()

    _session, token = await auth_service.issue_session(
        fixtures.session, user, app.state.auth.settings
    )
    await fixtures.session.commit()

    async with app_client(app) as client:
        client.cookies.set("api_session", token)
        response = await client.post(
            "/api/projects/" + project.public_id + "/environments",
            json={"name": "Account testing", "kind": "testing", "baseUrl": "https://account.test"},
        )

    assert response.status_code == 201
    assert any(
        item["name"] == "Account testing" and item["kind"] == "testing"
        for item in response.json()["environments"]
    )
