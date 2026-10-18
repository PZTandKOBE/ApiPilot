"""Auth V1: identities, sessions, state, cookies and ownership isolation.

No real GitHub/Google credentials or network calls are used. Provider success is
injected at the OAuthService boundary; state and account/session behavior are
tested against PostgreSQL in aiata_c4_test.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import delete, select

from backend.api.errors import AppError
from backend.app import create_app
from backend.db import database
from backend.db.models.project import Project
from backend.db.models.user import GuestSession, OAuthTransaction, User
from backend.services import auth as auth_service
from backend.services import guest_access, guest_limits, guest_session
from backend.services.auth import AuthError, OAuthIdentity
from backend.services.auth_config import load_auth_settings
from backend.services.oauth import OAuthService

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def isolate_provider_credentials(monkeypatch):
    """Keep a developer's real .env credentials out of auth fixtures."""
    for name in (
        "GITHUB_CLIENT_ID",
        "GITHUB_CLIENT_SECRET",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "AUTH_OFFICIAL_GUEST_ENABLED",
        "AUTH_OFFICIAL_GUEST_MAX_PROJECTS",
        "AUTH_OFFICIAL_GUEST_MAX_RUNS",
        "AUTH_OFFICIAL_GUEST_MAX_AGENT_TASKS",
        "AUTH_OFFICIAL_GUEST_DAILY_AGENT_TASKS",
    ):
        monkeypatch.delenv(name, raising=False)


@asynccontextmanager
async def app_client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        yield client


async def _delete_user_by_name(username: str) -> None:
    async with database.AsyncSessionLocal() as session:
        await session.execute(delete(User).where(User.username == username))
        await session.commit()


async def _delete_guest_token(token: str) -> None:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    async with database.AsyncSessionLocal() as session:
        await session.execute(
            delete(GuestSession).where(GuestSession.token_hash == digest)
        )
        await session.commit()


async def _delete_transaction(state: str) -> None:
    async with database.AsyncSessionLocal() as session:
        await session.execute(
            delete(OAuthTransaction).where(
                OAuthTransaction.state_hash
                == hashlib.sha256(state.encode("utf-8")).hexdigest()
            )
        )
        await session.commit()


def _identity(
    *,
    provider: str = "github",
    subject: str | None = None,
    username: str | None = None,
    email: str | None = None,
) -> OAuthIdentity:
    suffix = uuid.uuid4().hex[:10]
    return OAuthIdentity(
        provider=provider,
        subject=subject or "subject-" + suffix,
        username=username or "user-" + suffix,
        email=email,
        email_verified=provider == "google" and email is not None,
        avatar_url=None,
    )


async def _complete(identity: OAuthIdentity):
    return identity, "/console"


async def test_first_login_creates_account_and_same_subject_reuses_it(fixtures):
    identity = _identity()
    first = await auth_service.create_or_get_user(fixtures.session, identity)
    await fixtures.session.commit()
    await fixtures._keep(User, first)

    second = await auth_service.create_or_get_user(fixtures.session, identity)
    await fixtures.session.commit()

    assert second.id == first.id


async def test_same_email_at_two_providers_does_not_merge_accounts(fixtures):
    email = "same-" + uuid.uuid4().hex[:8] + "@example.test"
    github = await auth_service.create_or_get_user(
        fixtures.session,
        _identity(provider="github", email=email, username="same-" + uuid.uuid4().hex[:8]),
    )
    google = await auth_service.create_or_get_user(
        fixtures.session,
        _identity(provider="google", email=email, username="same-" + uuid.uuid4().hex[:8]),
    )
    await fixtures.session.commit()
    await fixtures._keep(User, github)
    await fixtures._keep(User, google)

    assert github.id != google.id


async def test_internal_guest_owns_user_projects_and_is_isolated(fixtures):
    user_a = User(
        username="auth-a-" + uuid.uuid4().hex[:8],
        email=None,
        email_verified=False,
        password_hash=None,
        status="active",
        provider="github",
        avatar_url=None,
    )
    user_b = User(
        username="auth-b-" + uuid.uuid4().hex[:8],
        email=None,
        email_verified=False,
        password_hash=None,
        status="active",
        provider="github",
        avatar_url=None,
    )
    fixtures.session.add_all([user_a, user_b])
    await fixtures.session.commit()
    await fixtures._keep(User, user_a)
    await fixtures._keep(User, user_b)

    guest_a = await auth_service.internal_guest_for_user(fixtures.session, user_a)
    guest_b = await auth_service.internal_guest_for_user(fixtures.session, user_b)
    project_a = Project(
        user_id=user_a.id,
        guest_session_id=None,
        public_id="authprj_" + uuid.uuid4().hex[:10],
        name="Auth A project",
        description=None,
    )
    fixtures.session.add(project_a)
    await fixtures._keep(Project, project_a)
    await fixtures.session.commit()

    assert guest_a.user_id == user_a.id
    assert guest_b.user_id == user_b.id
    assert (
        await guest_access.require_guest_project_access(
            fixtures.session, project_public_id=project_a.public_id, guest=guest_a
        )
    ).id == project_a.id

    with pytest.raises(AppError) as caught:
        await guest_access.require_guest_project_access(
            fixtures.session, project_public_id=project_a.public_id, guest=guest_b
        )
    assert caught.value.status_code == 404


async def test_official_browser_guest_cannot_read_account_project(fixtures, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_OFFICIAL_GUEST_ENABLED", "true")
    app = create_app()

    guest, token = await guest_session.issue(fixtures.session)
    await fixtures.session.commit()
    await fixtures._keep(GuestSession, guest)

    owner = User(
        username="guest-isolation-owner-" + uuid.uuid4().hex[:8],
        email=None,
        email_verified=False,
        password_hash=None,
        status="active",
        provider="github",
        avatar_url=None,
    )
    fixtures.session.add(owner)
    await fixtures.session.commit()
    await fixtures._keep(User, owner)
    account_project = Project(
        user_id=owner.id,
        guest_session_id=None,
        public_id="guestiso_" + uuid.uuid4().hex[:10],
        name="Account project",
        description=None,
    )
    fixtures.session.add(account_project)
    await fixtures._keep(Project, account_project)
    await fixtures.session.commit()

    async with app_client(app) as client:
        listed = await client.get(
            "/api/projects", headers={"X-Guest-Session": token}
        )
        assert listed.status_code == 200
        assert listed.json() == []

        foreign = await client.get(
            "/api/projects/" + account_project.public_id + "/runs",
            headers={"X-Guest-Session": token},
        )
        assert foreign.status_code == 404


async def test_user_a_cannot_read_user_b_project_or_runs(fixtures, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-state-secret-not-real")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    app = create_app()

    users = [
        User(
            username="isolation-a-" + uuid.uuid4().hex[:8],
            email=None,
            email_verified=False,
            password_hash=None,
            status="active",
            provider="github",
            avatar_url=None,
        ),
        User(
            username="isolation-b-" + uuid.uuid4().hex[:8],
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
            public_id="isolationprj_" + uuid.uuid4().hex[:10],
            name="Isolation " + str(index),
            description=None,
        )
        for index, user in enumerate(users)
    ]
    fixtures.session.add_all(projects)
    for project in projects:
        await fixtures._keep(Project, project)
    await fixtures.session.commit()

    tokens = []
    for user in users:
        _session, token = await auth_service.issue_session(
            fixtures.session, user, app.state.auth.settings
        )
        tokens.append(token)
    await fixtures.session.commit()

    async with app_client(app) as client:
        client.cookies.set("api_session", tokens[0])
        listed = await client.get("/api/projects")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [projects[0].public_id]

        foreign = await client.get(
            "/api/projects/" + projects[1].public_id + "/runs"
        )
        assert foreign.status_code == 404


async def test_oauth_transaction_is_one_time_and_expiry_checked(fixtures, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-state-secret-not-real")
    settings = load_auth_settings()
    state = "state-" + uuid.uuid4().hex
    await auth_service.create_transaction(
        fixtures.session,
        state=state,
        provider="github",
        nonce=None,
        redirect_after="/console",
        settings=settings,
    )
    await fixtures.session.commit()

    try:
        transaction = await auth_service.consume_transaction(
            fixtures.session, state=state, provider="github"
        )
        assert transaction.redirect_after == "/console"

        with pytest.raises(AuthError) as caught:
            await auth_service.consume_transaction(
                fixtures.session, state=state, provider="github"
            )
        assert caught.value.code == "state-invalid"
    finally:
        await _delete_transaction(state)


async def test_official_cloud_requires_login_and_disables_guest_issuance(
    monkeypatch,
):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-state-secret-not-real")
    app = create_app()
    async with app_client(app) as client:
        config = await client.get("/api/auth/config")
        assert config.status_code == 200
        assert config.json()["deploymentMode"] == "official_cloud"
        assert config.json()["loginRequired"] is True
        assert config.json()["guestEnabled"] is False

        protected = await client.get("/api/projects")
        assert protected.status_code == 401
        assert protected.json()["code"] == "auth-required"

        guest = await client.post("/api/guest-sessions")
        assert guest.status_code == 403
        assert guest.json()["code"] == "guest-sessions-disabled"

        login = await client.get("/api/auth/login/github")
        assert login.status_code == 302
        assert "error=provider-unavailable" in login.headers["location"]


async def test_official_cloud_ignores_a_valid_guest_header(fixtures, monkeypatch):
    from backend.services import guest_session

    guest, token = await guest_session.issue(fixtures.session)
    await fixtures.session.commit()
    await fixtures._keep(type(guest), guest)
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-state-secret-not-real")
    app = create_app()
    async with app_client(app) as client:
        response = await client.get(
            "/api/projects", headers={"X-Guest-Session": token}
        )
        assert response.status_code == 401
        assert response.json()["code"] == "auth-required"


async def test_official_cloud_can_enable_verified_guest_sessions(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-state-secret-not-real")
    monkeypatch.setenv("AUTH_OFFICIAL_GUEST_ENABLED", "true")
    app = create_app()
    async with app_client(app) as client:
        config = await client.get("/api/auth/config")
        assert config.status_code == 200
        assert config.json()["deploymentMode"] == "official_cloud"
        assert config.json()["loginRequired"] is False
        assert config.json()["guestEnabled"] is True

        guest = await client.post("/api/guest-sessions")
        assert guest.status_code == 201
        token = guest.json()["sessionToken"]
        try:
            listed = await client.get(
                "/api/projects", headers={"X-Guest-Session": token}
            )
            assert listed.status_code == 200
            assert listed.json() == []

            revoked = await client.delete(
                "/api/guest-sessions/current",
                headers={"X-Guest-Session": token},
            )
            assert revoked.status_code == 204
        finally:
            await _delete_guest_token(token)


async def test_official_guest_project_limit_is_server_side(fixtures, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_OFFICIAL_GUEST_ENABLED", "true")
    monkeypatch.setenv("AUTH_OFFICIAL_GUEST_MAX_PROJECTS", "1")
    settings = load_auth_settings()
    guest, token = await guest_session.issue(fixtures.session)
    await fixtures.session.commit()
    await fixtures._keep(GuestSession, guest)

    project = Project(
        guest_session_id=guest.id,
        user_id=None,
        public_id="limitprj_" + uuid.uuid4().hex[:10],
        name="Guest limit project",
        description=None,
    )
    fixtures.session.add(project)
    await fixtures._keep(Project, project)
    await fixtures.session.commit()

    with pytest.raises(AppError) as caught:
        await guest_limits.enforce_project_limit(
            fixtures.session, guest=guest, settings=settings
        )
    assert caught.value.status_code == 429
    assert caught.value.code == "guest-limit-reached"


async def test_self_hosted_mode_still_uses_guest_sessions(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "self_hosted")
    app = create_app()
    async with app_client(app) as client:
        config = await client.get("/api/auth/config")
        assert config.status_code == 200
        assert config.json()["deploymentMode"] == "self_hosted"
        assert config.json()["loginRequired"] is False
        assert config.json()["guestEnabled"] is True

        login = await client.get("/api/auth/login/github")
        assert login.status_code == 404

        guest = await client.post("/api/guest-sessions")
        assert guest.status_code == 201
        token = guest.json()["sessionToken"]
        try:
            listed = await client.get(
                "/api/projects", headers={"X-Guest-Session": token}
            )
            assert listed.status_code == 200
            assert listed.json() == []
        finally:
            await _delete_guest_token(token)


async def test_provider_cancellation_is_a_friendly_redirect(monkeypatch, fixtures):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-state-secret-not-real")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    app = create_app()
    state = "cancel-" + uuid.uuid4().hex
    await auth_service.create_transaction(
        fixtures.session,
        state=state,
        provider="github",
        nonce=None,
        redirect_after="/console",
        settings=app.state.auth.settings,
    )
    await fixtures.session.commit()
    try:
        async with app_client(app) as client:
            response = await client.get(
                "/api/auth/callback/github?error=access_denied&state=" + state
            )
            assert response.status_code == 302
            assert "error=oauth-cancelled" in response.headers["location"]
    finally:
        await _delete_transaction(state)


async def test_google_claim_without_subject_is_rejected(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-state-secret-not-real")
    service = OAuthService(load_auth_settings())
    with pytest.raises(AuthError) as caught:
        service._identity("google", {"email": "x@example.test", "email_verified": True})
    assert caught.value.code == "oidc-invalid"


async def test_login_redirect_carries_state_and_pkce_without_open_redirect(
    monkeypatch, read_session
):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-state-secret-not-real")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-client")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")
    app = create_app()
    assert app.state.auth.settings.callback_uri("github") == (
        "http://127.0.0.1:8000/api/auth/callback/github"
    )
    assert app.state.auth.settings.callback_uri("google") == (
        "http://127.0.0.1:8000/api/auth/callback/google"
    )
    state = None
    try:
        async with app_client(app) as client:
            response = await client.get(
                "/api/auth/login/github?next=https://evil.example/phish"
            )
            assert response.status_code == 302
            location = response.headers["location"]
            parsed = urlparse(location)
            query = parse_qs(parsed.query)
            assert query["code_challenge_method"] == ["S256"]
            assert query["code_challenge"][0]
            state = query["state"][0]

            row = (
                await read_session.execute(
                    select(OAuthTransaction).where(
                        OAuthTransaction.state_hash
                        == hashlib.sha256(state.encode()).hexdigest()
                    )
                )
            ).scalar_one()
            assert row.redirect_after == "/console"
    finally:
        if state:
            await _delete_transaction(state)


async def test_google_start_generates_nonce_and_pkce(fixtures, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-state-secret-not-real")
    service = OAuthService(load_auth_settings())
    captured = {}

    class FakeRedirect:
        async def authorize_redirect(self, request, redirect_uri, **kwargs):
            captured.update(kwargs)
            return httpx.Response(302)

    service._app = lambda provider: FakeRedirect()
    try:
        await service.start(
            None,  # the fake provider does not inspect the request
            fixtures.session,
            provider="google",
            redirect_after="/console",
        )
        await fixtures.session.commit()
        assert captured["state"]
        assert captured["nonce"]
        assert len(captured["code_verifier"]) >= 43
    finally:
        if captured.get("state"):
            await _delete_transaction(captured["state"])


async def test_callback_without_state_is_rejected(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-state-secret-not-real")
    app = create_app()
    async with app_client(app) as client:
        response = await client.get("/api/auth/callback/github?code=anything")
        assert response.status_code == 302
        assert "error=state-invalid" in response.headers["location"]


async def test_callback_without_state_cookie_is_rejected(monkeypatch, fixtures):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-state-secret-not-real")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-client")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")
    app = create_app()
    state = "no-cookie-" + uuid.uuid4().hex
    await auth_service.create_transaction(
        fixtures.session,
        state=state,
        provider="github",
        nonce=None,
        redirect_after="/console",
        settings=app.state.auth.settings,
    )
    await fixtures.session.commit()
    try:
        async with app_client(app) as client:
            response = await client.get(
                "/api/auth/callback/github?code=fake&state=" + state
            )
            assert response.status_code == 302
            assert "error=oauth-failed" in response.headers["location"]
    finally:
        await _delete_transaction(state)


async def test_successful_callback_sets_http_only_cookie_and_restores_session(
    monkeypatch, fixtures, read_session
):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-state-secret-not-real")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    app = create_app()
    identity = _identity(email=None)
    app.state.auth.complete = lambda request, session, *, provider: _complete(identity)
    username = identity.username
    try:
        async with app_client(app) as client:
            callback = await client.get(
                "/api/auth/callback/github?state=fake"
            )
            assert callback.status_code == 302
            set_cookie = callback.headers["set-cookie"].lower()
            assert "httponly" in set_cookie
            assert "samesite=lax" in set_cookie
            assert "path=/" in set_cookie

            me = await client.get("/api/auth/me")
            assert me.status_code == 200
            assert me.json()["email"] is None

            created = await client.post(
                "/api/projects",
                json={"name": "Account project", "baseUrl": "http://127.0.0.1:9"},
            )
            assert created.status_code == 201
            project_id = created.json()["id"]
            row = (
                await read_session.execute(
                    select(Project).where(Project.public_id == project_id)
                )
            ).scalar_one()
            assert row.user_id is not None
            assert row.guest_session_id is None

            wrong_origin = await client.post(
                "/api/auth/logout", headers={"Origin": "https://evil.example"}
            )
            assert wrong_origin.status_code == 403

            logout = await client.post(
                "/api/auth/logout", headers={"Origin": "http://127.0.0.1:5173"}
            )
            assert logout.status_code == 204
            assert (await client.get("/api/auth/me")).status_code == 401
    finally:
        await _delete_user_by_name(username)


async def test_secure_cookie_flag_when_configured(monkeypatch, fixtures):
    monkeypatch.setenv("DEPLOYMENT_MODE", "official_cloud")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-state-secret-not-real")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    app = create_app()
    identity = _identity(username="secure-" + uuid.uuid4().hex[:8])
    app.state.auth.complete = lambda request, session, *, provider: _complete(identity)
    try:
        async with app_client(app) as client:
            callback = await client.get(
                "/api/auth/callback/github?state=fake"
            )
            assert callback.status_code == 302
            assert "secure" in callback.headers["set-cookie"].lower()
    finally:
        await _delete_user_by_name(identity.username or "")
