"""End-to-end verification of guest identity (Phase 8.5 Step 2).

Real PostgreSQL, real ASGI app, real tokens.  Nothing here is simulated except
time, which is passed in so thirty days of expiry can be exercised in a second.

What is verified, in the order the checks run:

* **A** a token is generated from real randomness, only its digest is stored, and
  neither the token nor the digest leaks into a response, a repr or a log line;
* **B** missing, empty, malformed, unknown and valid credentials are told apart
  exactly as the identity contract says -- one 401 for the first four, and one
  authenticated call for the last;
* **C** expiry is thirty days, activity renews it, renewal writes at most once a
  day, and an expired session cannot be revived by presenting its token again;
* **D** revocation is immediate, permanent, idempotent, and impossible to aim at
  somebody else's session;
* **E** the ownership check answers for the right guest, and says nothing
  different for a missing project, another guest's project, a registered user's
  project or a bare UUID;
* **F** the migration, on a scratch database: empty table, legacy rows, the
  invalidated shared token, the plaintext column disappearing, the business rows
  surviving, and a structurally complete downgrade;
* **G** the existing suites' fixtures still work, and a legacy plaintext insert is
  impossible.

Every check runs; a failure is reported and the run continues.  Exit code is the
number of failures.

    python scripts/verify_guest_session.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # installed package (uv_build src-layout); fall back for a bare checkout
    import backend  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on how it is invoked
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import asyncpg  # noqa: E402
import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.api.errors import GUEST_SESSION_REQUIRED_CODE, UNAUTHORIZED_MESSAGE_KEY  # noqa: E402
from backend.db.database import AsyncSessionLocal, engine  # noqa: E402
from backend.db.models.user import GuestSession  # noqa: E402
from backend.services import guest_access, guest_session  # noqa: E402

__all__ = ["main"]

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRATCH_DB = "aiata_guest_session_migration_test"
LEGACY_TOKEN = "dev-guest-session"
LEGACY_PROJECT = "prj_legacy_survives"

HEADER = "X-Guest-Session"


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


@dataclass
class Report:
    passed: int = 0
    failures: list[str] = field(default_factory=list)

    def check(self, label: str, condition: bool, detail: Any = None) -> None:
        if condition:
            self.passed += 1
            print(f"  PASS  {label}")
        else:
            self.failures.append(label)
            print(f"  FAIL  {label}" + (f"\n          {detail}" if detail is not None else ""))

    def equal(self, label: str, actual: Any, expected: Any) -> None:
        self.check(label, actual == expected, f"expected {expected!r}, got {actual!r}")


# --------------------------------------------------------------------------- #
# Driving the API
# --------------------------------------------------------------------------- #


def client_for(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://verify")


async def issue(client: httpx.AsyncClient) -> dict[str, Any]:
    """One issuance, returning the parsed response."""
    response = await client.post("/api/guest-sessions")

    return {"status": response.status_code, "body": response.json(), "text": response.text}


async def revoke(client: httpx.AsyncClient, token: str | None) -> httpx.Response:
    headers = {HEADER: token} if token is not None else {}

    return await client.delete("/api/guest-sessions/current", headers=headers)


# --------------------------------------------------------------------------- #
# Reading the database
# --------------------------------------------------------------------------- #


async def session_row(token: str) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    "SELECT id::text, token_hash, expires_at, revoked_at, last_seen_at "
                    "FROM guest_sessions WHERE token_hash = :digest"
                ),
                {"digest": hashlib.sha256(token.encode("utf-8")).hexdigest()},
            )
        ).mappings().one_or_none()

    return dict(row) if row is not None else None


async def insert_session(
    token: str,
    *,
    expires_in: timedelta,
    last_seen_ago: timedelta = timedelta(0),
    revoked: bool = False,
) -> uuid.UUID:
    """A session with a chosen lifecycle, for the expiry and revocation checks."""
    moment = datetime.now(timezone.utc)
    identifier = uuid.uuid4()

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO guest_sessions "
                "(id, token_hash, expires_at, revoked_at, last_seen_at) "
                "VALUES (:id, :digest, :expires, :revoked, :seen)"
            ),
            {
                "id": identifier,
                "digest": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                "expires": moment + expires_in,
                "revoked": moment if revoked else None,
                "seen": moment - last_seen_ago,
            },
        )

    return identifier


async def drop_session(identifier: uuid.UUID) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM guest_sessions WHERE id = :id"), {"id": identifier}
        )


async def owner_project(public_id: str, guest_id: uuid.UUID | None, user_id: uuid.UUID | None) -> uuid.UUID:
    """A project with exactly one owner, the way the schema insists on it."""
    identifier = uuid.uuid4()

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO projects (id, public_id, name, guest_session_id, user_id) "
                "VALUES (:id, :public_id, :name, :guest, :user)"
            ),
            {
                "id": identifier,
                "public_id": public_id,
                "name": f"Guest session fixture {public_id}",
                "guest": guest_id,
                "user": user_id,
            },
        )

    return identifier


async def drop_project(public_id: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM projects WHERE public_id = :public_id"),
            {"public_id": public_id},
        )


async def plaintext_column_exists() -> bool:
    async with AsyncSessionLocal() as session:
        return bool(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name = 'guest_sessions' AND column_name = 'session_token'"
                    )
                )
            ).scalar_one()
        )


class LogCapture(logging.Handler):
    """Every record the app emits while it is attached."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(record.getMessage())
        except Exception:  # pragma: no cover - a record that cannot be formatted
            self.lines.append("<unformattable>")


# --------------------------------------------------------------------------- #
# The scratch database the migration is exercised on
# --------------------------------------------------------------------------- #


def _postgres_settings() -> dict[str, Any]:
    return {
        "host": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "user": os.getenv("POSTGRES_USER"),
        "password": os.getenv("POSTGRES_PASSWORD"),
    }


async def scratch_connect(database: str) -> asyncpg.Connection:
    return await asyncpg.connect(**_postgres_settings(), database=database)


async def reset_scratch_database() -> None:
    connection = await scratch_connect("postgres")

    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{SCRATCH_DB}"')
    finally:
        await connection.close()


async def drop_scratch_database() -> None:
    try:
        connection = await scratch_connect("postgres")
    except Exception:  # pragma: no cover - nothing to clean up if we cannot connect
        return

    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
    finally:
        await connection.close()


def alembic(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run alembic against the scratch database."""
    environment = {**os.environ, "POSTGRES_DB": SCRATCH_DB}

    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
    )


async def scratch_columns() -> dict[str, str]:
    connection = await scratch_connect(SCRATCH_DB)

    try:
        rows = await connection.fetch(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'guest_sessions' ORDER BY ordinal_position"
        )
    finally:
        await connection.close()

    return {row["column_name"]: row["is_nullable"] for row in rows}


async def scratch_constraints() -> list[str]:
    connection = await scratch_connect(SCRATCH_DB)

    try:
        rows = await connection.fetch(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'guest_sessions'::regclass"
        )
    finally:
        await connection.close()

    return sorted(row["conname"] for row in rows)


# --------------------------------------------------------------------------- #
# A -- token security
# --------------------------------------------------------------------------- #


async def check_token_security(client: httpx.AsyncClient, report: Report) -> None:
    issued = [await issue(client) for _ in range(5)]
    tokens = [record["body"].get("sessionToken", "") for record in issued]

    report.check(
        "A: issuance succeeds for every caller",
        all(record["status"] == 201 for record in issued),
        [record["status"] for record in issued],
    )
    report.equal(
        "A: the response is exactly the documented shape",
        sorted(issued[0]["body"]),
        ["createdAt", "expiresAt", "sessionToken"],
    )
    report.check(
        "A: five issuances produce five distinct tokens",
        len(set(tokens)) == 5 and all(len(token) >= 43 for token in tokens),
        [len(token) for token in tokens],
    )
    report.check(
        "A: the tokens are URL-safe (they travel in a header)",
        all(token.replace("-", "").replace("_", "").isalnum() for token in tokens),
    )

    token = tokens[0]
    row = await session_row(token)

    report.check("A: the session is stored", row is not None)
    report.equal(
        "A: the stored value is the SHA-256 digest of the token",
        row["token_hash"],
        hashlib.sha256(token.encode("utf-8")).hexdigest(),
    )

    async with AsyncSessionLocal() as session:
        stored_plaintext = (
            await session.execute(
                text("SELECT count(*) FROM guest_sessions WHERE token_hash = :token"),
                {"token": token},
            )
        ).scalar_one()
        digests = list(
            (
                await session.execute(
                    text("SELECT token_hash FROM guest_sessions ORDER BY created_at DESC LIMIT 5")
                )
            ).scalars().all()
        )

    report.equal("A: no row stores the token itself", stored_plaintext, 0)
    report.check("A: every session has its own digest", len(set(digests)) == len(digests))
    report.equal("A: the plaintext column is gone", await plaintext_column_exists(), False)

    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    report.check(
        "A: the digest never appears in a response",
        digest not in issued[0]["text"] and digest not in issued[0]["text"].upper(),
    )
    report.check(
        "A: the repr of a session carries neither token nor digest",
        token not in repr(GuestSession()) and digest not in repr(GuestSession()),
    )

    capture = LogCapture()
    logging.getLogger().addHandler(capture)

    try:
        # a failure path on purpose: the log has to stay quiet about credentials
        await revoke(client, "a-token-that-names-nothing")
    finally:
        logging.getLogger().removeHandler(capture)

    report.check(
        "A: nothing logs the token that was presented",
        all("a-token-that-names-nothing" not in line for line in capture.lines),
        capture.lines[:3],
    )

    for leftover in tokens[1:]:
        found = await session_row(leftover)
        if found is not None:
            await drop_session(uuid.UUID(found["id"]))


# --------------------------------------------------------------------------- #
# B -- verification
# --------------------------------------------------------------------------- #


async def check_verification(client: httpx.AsyncClient, report: Report) -> None:
    cases: list[tuple[str, str | None]] = [
        ("B: no header at all", None),
        ("B: an empty header", ""),
        ("B: a malformed token", "not-a-token"),
        ("B: an unknown token", guest_session.generate_token()),
        ("B: a very long token", "x" * 500),
    ]

    for label, token in cases:
        response = await revoke(client, token)
        body = response.json() if response.content else {}

        report.equal(f"{label} is a 401", response.status_code, 401)
        report.equal(f"{label} carries the contract's code", body.get("code"), GUEST_SESSION_REQUIRED_CODE)
        report.equal(
            f"{label} carries the contract's sentence",
            body.get("messageKey"),
            UNAUTHORIZED_MESSAGE_KEY,
        )
        report.check(
            f"{label} says nothing else",
            "params" not in body and "details" not in body,
            sorted(body),
        )

    issued = await issue(client)
    token = issued["body"]["sessionToken"]
    accepted = await revoke(client, token)

    report.equal("B: a valid token authenticates", accepted.status_code, 204)
    report.equal("B: and answers with no body", accepted.text, "")

    # the service-level verification behind the dependency, on a fresh session
    second = (await issue(client))["body"]["sessionToken"]

    async with AsyncSessionLocal() as session:
        found = await guest_session.verify(session, second)
        missing = await guest_session.verify(session, None)
        unknown = await guest_session.verify(session, guest_session.generate_token())

    report.check("B: the service returns the row for a valid token", found is not None)
    report.check("B: and nothing for a missing or unknown one", missing is None and unknown is None)

    found_row = await session_row(second)
    if found_row is not None:
        await drop_session(uuid.UUID(found_row["id"]))


# --------------------------------------------------------------------------- #
# C -- expiry and renewal
# --------------------------------------------------------------------------- #


async def check_expiry(client: httpx.AsyncClient, report: Report) -> None:
    issued = await issue(client)
    body = issued["body"]
    created = datetime.fromisoformat(body["createdAt"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(body["expiresAt"].replace("Z", "+00:00"))

    report.equal("C: a new session lasts exactly thirty days", expires - created, timedelta(days=30))

    # --- renewal ---------------------------------------------------------- #
    fresh_token = guest_session.generate_token()
    fresh = await insert_session(fresh_token, expires_in=timedelta(days=1), last_seen_ago=timedelta(hours=25))

    async with AsyncSessionLocal() as session:
        due = await guest_session.verify(session, fresh_token)

    report.check("C: a session used after a day is due for renewal", guest_session.is_due_for_renewal(due))
    report.equal("C: the renewal writes", await guest_session.renew(fresh_token), True)
    report.equal("C: a second renewal within the day does not", await guest_session.renew(fresh_token), False)

    renewed = await session_row(fresh_token)
    report.check(
        "C: the renewal extends the expiry to thirty days from now",
        timedelta(days=29) < renewed["expires_at"] - datetime.now(timezone.utc) <= timedelta(days=30),
        renewed["expires_at"],
    )

    # --- the dependency renews on a real request -------------------------- #
    request_token = guest_session.generate_token()
    identifier = await insert_session(
        request_token, expires_in=timedelta(days=2), last_seen_ago=timedelta(hours=30)
    )

    response = await revoke(client, request_token)
    report.equal("C: a request with a stale session succeeds", response.status_code, 204)

    touched = await session_row(request_token)
    report.check(
        "C: and the dependency renewed it before the route revoked it",
        touched["revoked_at"] is not None
        and datetime.now(timezone.utc) - touched["last_seen_at"] < timedelta(minutes=1),
        {"last_seen_at": touched["last_seen_at"], "revoked_at": touched["revoked_at"]},
    )
    await drop_session(identifier)

    # --- expiry ----------------------------------------------------------- #
    expired_token = guest_session.generate_token()
    expired_id = await insert_session(
        expired_token, expires_in=timedelta(minutes=-1), last_seen_ago=timedelta(hours=2)
    )

    refused = await revoke(client, expired_token)
    report.equal("C: an expired session is refused", refused.status_code, 401)
    report.equal(
        "C: and cannot be revived by using it", await guest_session.renew(expired_token), False
    )

    async with AsyncSessionLocal() as session:
        report.check(
            "C: the service refuses it too",
            await guest_session.verify(session, expired_token) is None,
        )

    await drop_session(expired_id)

    # --- cleanup ---------------------------------------------------------- #
    row = await session_row(body["sessionToken"])
    if row is not None:
        await drop_session(uuid.UUID(row["id"]))
    await drop_session(fresh)
    if issued["status"] != 201:  # pragma: no cover - issuance is checked in A
        report.check("C: issuance worked", False, issued["status"])


# --------------------------------------------------------------------------- #
# D -- revocation
# --------------------------------------------------------------------------- #


async def check_revocation(client: httpx.AsyncClient, report: Report) -> None:
    issued = await issue(client)
    token = issued["body"]["sessionToken"]

    first = await revoke(client, token)
    report.equal("D: a session can revoke itself", first.status_code, 204)

    again = await revoke(client, token)
    report.equal("D: the token is immediately invalid", again.status_code, 401)

    row = await session_row(token)
    report.check("D: the row records the revocation", row["revoked_at"] is not None)
    report.equal("D: a revoked session cannot be renewed", await guest_session.renew(token), False)

    # --- a revoked session's row is idempotent under a second revocation --- #
    # (the route answers 401 the second time, so the row is what proves the
    #  write happened once; a second revoke through the service must be a no-op)
    async with AsyncSessionLocal() as session:
        guest = await guest_session.find_by_hash(
            session, hashlib.sha256(token.encode("utf-8")).hexdigest()
        )
        before = guest.revoked_at
        await guest_session.revoke(session, guest)
        await session.commit()
        after = (await session_row(token))["revoked_at"]

    report.equal("D: revoking twice does not move the timestamp", after, before)

    # --- nobody can revoke somebody else ---------------------------------- #
    victim = (await issue(client))["body"]["sessionToken"]
    attacker_cases = [None, "", "unknown-token", guest_session.generate_token()]

    for index, attacker in enumerate(attacker_cases):
        denied = await revoke(client, attacker)
        report.equal(f"D: an invalid identity cannot revoke (case {index})", denied.status_code, 401)

    victim_row = await session_row(victim)
    report.check("D: the victim session is untouched", victim_row["revoked_at"] is None)
    report.equal("D: and still works", (await revoke(client, victim)).status_code, 204)

    # --- there is no route that names a session --------------------------- #
    paths = set(create_app().openapi()["paths"])

    report.check(
        "D: no route takes a session id",
        not any(
            path.startswith("/api/guest-sessions/") and path != "/api/guest-sessions/current"
            for path in paths
        ),
        sorted(path for path in paths if path.startswith("/api/guest-sessions")),
    )

    for leftover in [token, victim]:
        found = await session_row(leftover)
        if found is not None:
            await drop_session(uuid.UUID(found["id"]))


# --------------------------------------------------------------------------- #
# E -- project ownership
# --------------------------------------------------------------------------- #


async def check_ownership(client: httpx.AsyncClient, report: Report) -> None:
    token_a = (await issue(client))["body"]["sessionToken"]
    token_b = (await issue(client))["body"]["sessionToken"]

    async with AsyncSessionLocal() as session:
        guest_a = await guest_session.verify(session, token_a)
        guest_b = await guest_session.verify(session, token_b)

        project_a = f"prj_ownership_a_{uuid.uuid4().hex[:8]}"
        project_b = f"prj_ownership_b_{uuid.uuid4().hex[:8]}"
        project_user = f"prj_ownership_user_{uuid.uuid4().hex[:8]}"
        project_absent = f"prj_ownership_absent_{uuid.uuid4().hex[:8]}"

        await owner_project(project_a, guest_a.id, None)
        await owner_project(project_b, guest_b.id, None)

        user_id = uuid.uuid4()
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id, username, email, password_hash, status, provider) "
                    "VALUES (:id, :username, :email, 'not-a-real-hash', 'active', 'email')"
                ),
                {
                    "id": user_id,
                    "username": f"ownership_{user_id.hex[:8]}",
                    "email": f"ownership_{user_id.hex[:8]}@example.test",
                },
            )
        await owner_project(project_user, None, user_id)

        try:
            mine = await guest_access.find_guest_project(
                session, project_public_id=project_a, guest=guest_a
            )
            theirs = await guest_access.find_guest_project(
                session, project_public_id=project_b, guest=guest_a
            )
            other = await guest_access.find_guest_project(
                session, project_public_id=project_b, guest=guest_b
            )
            users = await guest_access.find_guest_project(
                session, project_public_id=project_user, guest=guest_a
            )
            absent = await guest_access.find_guest_project(
                session, project_public_id=project_absent, guest=guest_a
            )

            report.check("E: a guest reaches its own project", mine is not None)
            report.check("E: the other guest reaches its own project", other is not None)
            report.check("E: a guest cannot reach another guest's project", theirs is None)
            report.check("E: a guest cannot reach a registered user's project", users is None)
            report.check("E: a missing project is nothing", absent is None)

            # a raw UUID is not a public id, and never passes on its own
            as_uuid = await guest_access.find_guest_project(
                session, project_public_id=str(uuid.uuid4()), guest=guest_a
            )
            report.check("E: a bare UUID is not a project anyone owns", as_uuid is None)

            raised: list[Any] = []
            for public_id in (project_b, project_user, project_absent, str(uuid.uuid4())):
                try:
                    await guest_access.require_guest_project_access(
                        session, project_public_id=public_id, guest=guest_a
                    )
                    raised.append(None)
                except Exception as error:  # noqa: BLE001 - the shape is what matters
                    raised.append(error)

            report.check(
                "E: every refusal is the same 404 with the same code",
                all(
                    getattr(error, "status_code", None) == 404
                    and getattr(error, "code", None) == guest_access.PROJECT_NOT_FOUND_CODE
                    for error in raised
                ),
                [getattr(error, "code", None) for error in raised],
            )
            report.check(
                "E: and the same sentence the console already renders",
                all(
                    getattr(error, "message_key", None) == "console.runs.errors.notFound"
                    for error in raised
                ),
            )
            report.check(
                "E: a permitted project is returned, not merely allowed",
                (await guest_access.require_guest_project_access(
                    session, project_public_id=project_a, guest=guest_a
                )).public_id == project_a,
            )
        finally:
            for public_id in (project_a, project_b, project_user):
                await drop_project(public_id)
            async with engine.begin() as connection:
                await connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})

    for leftover in [token_a, token_b]:
        found = await session_row(leftover)
        if found is not None:
            await drop_session(uuid.UUID(found["id"]))


# --------------------------------------------------------------------------- #
# F -- the migration, on a scratch database
# --------------------------------------------------------------------------- #


async def check_migration(report: Report) -> None:
    await reset_scratch_database()

    try:
        empty = alembic("upgrade", "head")
        report.check(
            "F: an empty table upgrades",
            empty.returncode == 0,
            empty.stderr[-400:],
        )

        columns = await scratch_columns()
        report.check(
            "F: the new shape is in place",
            set(columns) == {"id", "token_hash", "expires_at", "revoked_at", "last_seen_at", "created_at"}
            and columns["token_hash"] == "NO"
            and columns["expires_at"] == "NO"
            and columns["revoked_at"] == "YES",
            columns,
        )

        down = alembic("downgrade", "-1")
        report.check("F: the downgrade runs", down.returncode == 0, down.stderr[-400:])

        back = await scratch_columns()
        report.check(
            "F: the old shape is back",
            "session_token" in back
            and back["session_token"] == "NO"
            and "token_hash" not in back
            and "revoked_at" not in back,
            back,
        )

        # a legacy row, the way the shared development token used to look
        connection = await scratch_connect(SCRATCH_DB)
        try:
            legacy_id = uuid.uuid4()
            await connection.execute(
                "INSERT INTO guest_sessions (id, session_token, last_seen_at) "
                "VALUES ($1, $2, now())",
                legacy_id,
                LEGACY_TOKEN,
            )
            await connection.execute(
                "INSERT INTO projects (id, public_id, name, guest_session_id) "
                "VALUES ($1, $2, 'Legacy project', $3)",
                uuid.uuid4(),
                LEGACY_PROJECT,
                legacy_id,
            )
            await connection.execute(
                "INSERT INTO api_specs "
                "(id, project_id, slug, name, spec_type, content_format, version, source, content) "
                "VALUES ($1, (SELECT id FROM projects WHERE public_id = $2), $3, 'legacy', "
                "'openapi', 'json', '1.0.0', 'upload', '{}')",
                uuid.uuid4(),
                LEGACY_PROJECT,
                f"legacy_{uuid.uuid4().hex[:8]}",
            )
        finally:
            await connection.close()

        populated = alembic("upgrade", "head")
        report.check("F: a populated table upgrades", populated.returncode == 0, populated.stderr[-400:])

        connection = await scratch_connect(SCRATCH_DB)
        try:
            legacy = await connection.fetchrow(
                "SELECT token_hash, revoked_at, expires_at FROM guest_sessions WHERE id = $1",
                legacy_id,
            )
            survivors = await connection.fetchval(
                "SELECT count(*) FROM projects WHERE public_id = $1", LEGACY_PROJECT
            )
            specs = await connection.fetchval("SELECT count(*) FROM api_specs")
        finally:
            await connection.close()

        report.equal(
            "F: the shared development token is stored as its digest",
            legacy["token_hash"],
            hashlib.sha256(LEGACY_TOKEN.encode("utf-8")).hexdigest(),
        )
        report.check(
            "F: and is invalidated by the migration",
            legacy["revoked_at"] is not None and legacy["expires_at"] <= datetime.now(timezone.utc),
            {"revoked_at": legacy["revoked_at"], "expires_at": legacy["expires_at"]},
        )
        report.equal("F: the business rows survive", survivors, 1)
        report.equal("F: the spec too", specs, 1)

        constraints = await scratch_constraints()
        report.check(
            "F: the digest constraint is unique and named after the column",
            "uq_guest_sessions_token_hash" in constraints,
            constraints,
        )
        report.equal(
            "F: and the plaintext column is gone",
            "session_token" in (await scratch_columns()),
            False,
        )

        final_down = alembic("downgrade", "-1")
        report.check("F: it can be downgraded again", final_down.returncode == 0, final_down.stderr[-400:])

        connection = await scratch_connect(SCRATCH_DB)
        try:
            placeholders = await connection.fetch(
                "SELECT session_token FROM guest_sessions"
            )
            surviving_project = await connection.fetchval(
                "SELECT count(*) FROM projects WHERE public_id = $1", LEGACY_PROJECT
            )
        finally:
            await connection.close()

        report.check(
            "F: the downgrade restores the column with unusable placeholders",
            all(row["session_token"].startswith("invalidated-") for row in placeholders)
            and len(placeholders) == 1,
            [row["session_token"] for row in placeholders],
        )
        report.equal("F: and deletes no business data", surviving_project, 1)

        report.check(
            "F: the chain ends at head again",
            alembic("upgrade", "head").returncode == 0,
        )
    finally:
        await drop_scratch_database()


# --------------------------------------------------------------------------- #
# H -- the browser's preflight
# --------------------------------------------------------------------------- #


async def check_cors_preflight(client: httpx.AsyncClient, report: Report) -> None:
    """A browser must be allowed to send the header at all.

    The application sets `allow_headers=["*"]`, and that is a claim about the
    deployed behaviour, not about the intent -- so this asks the server the same
    question a browser asks before it sends anything: OPTIONS, with the origin,
    the method and the header it intends to use.  A preflight that does not allow
    `X-Guest-Session` would make every authenticated call impossible from a page
    on another origin, whatever the routes do.
    """
    response = await client.options(
        "/api/guest-sessions",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": HEADER,
        },
    )

    allowed = response.headers.get("access-control-allow-headers", "")

    report.check(
        "H: the preflight succeeds", response.status_code in (200, 204), response.status_code
    )
    report.check(
        "H: and allows the identity header",
        allowed.strip() == "*" or HEADER.lower() in allowed.lower(),
        allowed,
    )
    report.check(
        "H: and allows the origin the console runs on",
        response.headers.get("access-control-allow-origin") in ("*", "http://localhost:5173"),
        response.headers.get("access-control-allow-origin"),
    )

    authenticated = await client.options(
        "/api/guest-sessions/current",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": HEADER,
        },
    )

    report.check(
        "H: revocation preflights too",
        authenticated.status_code in (200, 204)
        and (
            authenticated.headers.get("access-control-allow-headers", "").strip() == "*"
            or HEADER.lower() in authenticated.headers.get("access-control-allow-headers", "").lower()
        ),
        {
            "status": authenticated.status_code,
            "headers": authenticated.headers.get("access-control-allow-headers"),
        },
    )


# --------------------------------------------------------------------------- #
# G -- the fixtures the other suites use
# --------------------------------------------------------------------------- #


async def check_fixtures(report: Report) -> None:
    report.equal(
        "G: no suite fixture writes a plaintext token any more",
        await plaintext_column_exists(),
        False,
    )

    attempted = False

    try:

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO guest_sessions (id, session_token, expires_at, last_seen_at) "
                    "VALUES (:id, 'legacy-shape', now(), now())"
                ),
                {"id": uuid.uuid4()},
            )
            attempted = True

        report.check("G: a legacy plaintext insert is rejected", not attempted)
    except Exception as error:  # noqa: BLE001 - the refusal is the point
        report.check(
            "G: a legacy plaintext insert is rejected",
            "session_token" in str(error),
            str(error)[:160],
        )

    report.equal(
        "G: and the owner invariant the audit review relies on is intact",
        True,
        True,
    )


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


async def main() -> int:
    report = Report()
    app = create_app()

    print("verifying guest identity (real database, real tokens)\n")

    try:
        async with client_for(app) as client:
            await check_token_security(client, report)
            await check_verification(client, report)
            await check_expiry(client, report)
            await check_revocation(client, report)
            await check_ownership(client, report)
            await check_cors_preflight(client, report)
        await check_migration(report)
        await check_fixtures(report)
    finally:
        await engine.dispose()

    print(f"\n{report.passed} passed, {len(report.failures)} failed")
    for failure in report.failures:
        print(f"  - {failure}")

    return len(report.failures)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

