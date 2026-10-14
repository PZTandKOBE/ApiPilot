"""Access control review for the agent task and audit routes (Phase 8.4 Step 2).

This suite answers one question with measurements rather than opinions: **what
does this service actually require of a caller before it hands over a task or an
audit?**

It creates the real rows the product's own model describes -- `users`,
`guest_sessions`, `projects` with exactly one owner -- then drives the real
ASGI app against a real PostgreSQL.  Nothing about ownership is simulated: the
fixtures are the rows the schema defines, and the probes are the requests the
frontend sends (which carry no credentials of any kind).

Three kinds of result appear:

* **checks** -- properties that must hold, and fail the run when they do not:
  the ownership invariant in the database, the audit never reaching outside its
  own task, and the error semantics of missing resources;
* **measurements** -- what the service *does* with a caller-supplied credential,
  recorded so that the review states a fact instead of an impression.  Each one
  is asserted against the behaviour observed today, so if enforcement ever lands
  these lines fail, and the next person has to read them;
* **findings** -- the conclusions, printed at the end.

Exit code is the number of failed checks.  A measurement is not a check: the
suite does not pretend a property is enforced because it is documented.

    python scripts/verify_agent_audit_access.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # installed package (uv_build src-layout); fall back for a bare checkout
    import backend  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on how it is invoked
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ["AGENT_ANALYZER"] = "deterministic"
os.environ["AGENT_PLANNER"] = "deterministic"
"""Access control is what this suite measures; the rule engine keeps it free of
model calls (and of a key)."""

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.db.database import AsyncSessionLocal, engine  # noqa: E402
from backend.services import agent_plan  # noqa: E402
from backend.services.spec_identity import hash_string, slugify  # noqa: E402

__all__ = ["main"]

PROJECTS = {
    "user_a": "prj_access_user_a",
    "user_b": "prj_access_user_b",
    "guest_a": "prj_access_guest_a",
    "guest_b": "prj_access_guest_b",
}

USER_TOKENS = {"user_a": "user-a@example.test", "user_b": "user-b@example.test"}
GUEST_TOKENS = {"guest_a": "guest-session-a-token", "guest_b": "guest-session-b-token"}

# The fixture stores the digest of each token, exactly as the service does, so
# the probes below still send a *genuine* -- valid, unexpired -- credential that
# belongs to somebody else.  Only the fixture changed in Phase 8.5 Step 2: the
# measurement it feeds is the same one, and it still records that the routes
# ignore the header.
GUEST_DIGESTS = {
    name: hashlib.sha256(token.encode("utf-8")).hexdigest()
    for name, token in GUEST_TOKENS.items()
}

TITLE = "Access Review API"


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


@dataclass
class Report:
    passed: int = 0
    failures: list[str] = field(default_factory=list)
    measurements: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)

    def check(self, label: str, condition: bool, detail: Any = None) -> None:
        if condition:
            self.passed += 1
            print(f"  PASS  {label}")
        else:
            self.failures.append(label)
            print(f"  FAIL  {label}" + (f"\n          {detail}" if detail is not None else ""))

    def equal(self, label: str, actual: Any, expected: Any) -> None:
        self.check(label, actual == expected, f"expected {expected!r}, got {actual!r}")

    def measured(self, label: str, observed: Any, expected_today: Any) -> None:
        """Record what the service does, and hold it to what it does today.

        An observation, not a promise: `expected_today` is the behaviour this
        review found, so the line fails the day enforcement changes it -- which
        is the point, because then this file has to be read again.
        """
        line = f"{label} -> {observed!r}"
        self.measurements.append(line)
        print(f"  MEASURED  {line}")

        if observed != expected_today:
            self.failures.append(f"{label} (behaviour changed)")
            print(
                f"          the service no longer behaves as this review recorded "
                f"({expected_today!r}); update the review"
            )

    def finding(self, text: str) -> None:
        self.findings.append(text)
        print(f"  FINDING  {text}")


# --------------------------------------------------------------------------- #
# The fixture: real owners, real projects
# --------------------------------------------------------------------------- #


def document_for(name: str) -> str:
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": f"{TITLE} {name}", "version": "1.0.0"},
            "paths": {
                "/orders": {
                    "get": {
                        "tags": ["orders"],
                        "summary": "List orders",
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
    )


def identity_for(name: str) -> tuple[str, str]:
    slug = f"{slugify(TITLE + ' ' + name)}_{hash_string(document_for(name))}"

    return f"spec_{slug}", f"plan_{slug}"


async def cleanup() -> None:
    """Remove everything this suite creates, in dependency order."""
    async with engine.begin() as connection:
        for public_id in PROJECTS.values():
            project_id = (
                await connection.execute(
                    text("SELECT id FROM projects WHERE public_id = :public_id"),
                    {"public_id": public_id},
                )
            ).scalar_one_or_none()

            if project_id is None:
                continue

            for statement in (
                "DELETE FROM test_runs WHERE project_id = :project",
                "DELETE FROM agent_tasks WHERE project_id = :project",
                "DELETE FROM test_plans WHERE project_id = :project",
                "DELETE FROM api_specs WHERE project_id = :project",
                "DELETE FROM environments WHERE project_id = :project",
                "DELETE FROM projects WHERE id = :project",
            ):
                await connection.execute(text(statement), {"project": project_id})

        for digest in GUEST_DIGESTS.values():
            await connection.execute(
                text("DELETE FROM guest_sessions WHERE token_hash = :digest"),
                {"digest": digest},
            )

        for email in USER_TOKENS.values():
            await connection.execute(
                text("DELETE FROM users WHERE email = :email"), {"email": email}
            )


async def ensure_fixture() -> None:
    """Four owners and four projects: two accounts, two guest sessions.

    Users and guest sessions are rows, because that is what they are in this
    product: there is no sign-up endpoint and no guest-token endpoint, so the
    only way a project comes to exist is the way the schema describes it.
    """
    await cleanup()

    async with engine.begin() as connection:
        for name, email in USER_TOKENS.items():
            user_id = (
                await connection.execute(
                    text(
                        "INSERT INTO users (id, username, email, password_hash, status, provider) "
                        "VALUES (:id, :username, :email, :password, 'active', 'email') RETURNING id"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "username": email.split("@")[0],
                        "email": email,
                        "password": "not-a-real-hash",
                    },
                )
            ).scalar_one()

            await connection.execute(
                text(
                    "INSERT INTO projects (id, public_id, name, user_id) "
                    "VALUES (:id, :public_id, :name, :user)"
                ),
                {
                    "id": uuid.uuid4(),
                    "public_id": PROJECTS[name],
                    "name": f"Access review {name}",
                    "user": user_id,
                },
            )

        for name, token in GUEST_TOKENS.items():
            guest_id = (
                await connection.execute(
                    text(
                        "INSERT INTO guest_sessions (id, token_hash, expires_at, last_seen_at) "
                        "VALUES (:id, :digest, now() + interval '30 days', now()) "
                        "RETURNING id"
                    ),
                    {"id": uuid.uuid4(), "digest": GUEST_DIGESTS[name]},
                )
            ).scalar_one()

            await connection.execute(
                text(
                    "INSERT INTO projects (id, public_id, name, guest_session_id) "
                    "VALUES (:id, :public_id, :name, :guest)"
                ),
                {
                    "id": uuid.uuid4(),
                    "public_id": PROJECTS[name],
                    "name": f"Access review {name}",
                    "guest": guest_id,
                },
            )

        for public_id in PROJECTS.values():
            project_id = (
                await connection.execute(
                    text("SELECT id FROM projects WHERE public_id = :public_id"),
                    {"public_id": public_id},
                )
            ).scalar_one()

            await connection.execute(
                text(
                    "INSERT INTO environments "
                    "(id, project_id, public_id, name, kind, base_url, is_default) "
                    "VALUES (:id, :project, :public_id, 'Access target', 'staging', "
                    "'http://127.0.0.1:1', true)"
                ),
                {
                    "id": uuid.uuid4(),
                    "project": project_id,
                    "public_id": f"env_{public_id}",
                },
            )


# --------------------------------------------------------------------------- #
# Driving the API
# --------------------------------------------------------------------------- #


async def create_task(
    client: httpx.AsyncClient, owner: str, *, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    """Create one agent task for that owner's project, through the real API."""
    name = owner
    spec_id, _ = identity_for(name)
    response = await client.post(
        f"/api/projects/{PROJECTS[owner]}/agent/tasks",
        headers=headers or {"X-Guest-Session": GUEST_TOKENS[owner]},
        json={
            "projectId": PROJECTS[owner],
            "specId": spec_id,
            "specDocument": document_for(name),
            "environmentId": f"env_{PROJECTS[owner]}",
            "prompt": f"Design a plan for {owner}.",
            "variables": {},
        },
    )

    return {"status": response.status_code, "body": response.json() if response.content else {}}


async def owner_rows() -> dict[str, dict[str, Any]]:
    """Each project with the owner it actually has, read back from the database."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT projects.public_id, "
                    "projects.user_id::text AS user_id, "
                    "projects.guest_session_id::text AS guest_session_id, "
                    "users.email AS user_email, "
                    "guest_sessions.id::text AS guest_token "
                    "FROM projects "
                    "LEFT JOIN users ON users.id = projects.user_id "
                    "LEFT JOIN guest_sessions ON guest_sessions.id = projects.guest_session_id "
                    "WHERE projects.public_id = ANY(:ids)"
                ),
                {"ids": list(PROJECTS.values())},
            )
        ).mappings().all()

    return {row["public_id"]: dict(row) for row in rows}


async def task_owner(task_id: str) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    "SELECT agent_tasks.id::text AS task_id, "
                    "projects.public_id AS project_public_id, "
                    "users.email AS user_email, "
                    "guest_sessions.id::text AS guest_token, "
                    "(SELECT count(*) FROM agent_task_audits "
                    " WHERE agent_task_audits.task_id = agent_tasks.id) AS audits "
                    "FROM agent_tasks "
                    "JOIN projects ON projects.id = agent_tasks.project_id "
                    "LEFT JOIN users ON users.id = projects.user_id "
                    "LEFT JOIN guest_sessions ON guest_sessions.id = projects.guest_session_id "
                    "WHERE agent_tasks.id = :task"
                ),
                {"task": uuid.UUID(task_id)},
            )
        ).mappings().one_or_none()

    return dict(row) if row is not None else None


# --------------------------------------------------------------------------- #
# User-owned resources: rows, not requests
#
# There is no user identity in this product -- sign-in is a later phase -- so a
# user-owned task cannot be created over HTTP at all, and this suite must not
# pretend otherwise.  What it can do is put the row there and check the boundary
# that *is* implemented: a guest must not reach it.
#
# The rows are cloned with SELECT * from a task the API itself created, so the
# fixture never encodes a column list that a later migration could invalidate.
# --------------------------------------------------------------------------- #


async def seed_user_tasks() -> dict[str, dict[str, Any]]:
    """One user-owned task (and audit) per account, copied from real rows."""
    seeded: dict[str, dict[str, Any]] = {}

    async with engine.begin() as connection:
        source = (
            await connection.execute(
                text("SELECT id FROM agent_tasks ORDER BY created_at LIMIT 1")
            )
        ).scalar_one()
        source_audit = (
            await connection.execute(text("SELECT id FROM agent_task_audits LIMIT 1"))
        ).scalar_one_or_none()

        for name in USER_TOKENS:
            task_id = uuid.uuid4()

            await connection.execute(
                text("CREATE TEMP TABLE clone_task AS SELECT * FROM agent_tasks WHERE id = :id"),
                {"id": source},
            )
            await connection.execute(
                text(
                    "UPDATE clone_task SET id = :new_id, "
                    "project_id = (SELECT id FROM projects WHERE public_id = :public_id)"
                ),
                {"new_id": task_id, "public_id": PROJECTS[name]},
            )
            await connection.execute(text("INSERT INTO agent_tasks SELECT * FROM clone_task"))
            await connection.execute(text("DROP TABLE clone_task"))

            if source_audit is not None:
                await connection.execute(
                    text(
                        "CREATE TEMP TABLE clone_audit AS "
                        "SELECT * FROM agent_task_audits WHERE id = :id"
                    ),
                    {"id": source_audit},
                )
                await connection.execute(
                    text("UPDATE clone_audit SET id = :new_id, task_id = :task_id"),
                    {"new_id": uuid.uuid4(), "task_id": task_id},
                )
                await connection.execute(
                    text("INSERT INTO agent_task_audits SELECT * FROM clone_audit")
                )
                await connection.execute(text("DROP TABLE clone_audit"))

            seeded[name] = {"status": 200, "body": {"id": str(task_id)}, "seeded": True}

    return seeded


async def check_user_owned_is_unreachable(
    client: httpx.AsyncClient, report: Report, accounts: dict[str, dict[str, Any]]
) -> None:
    """D: the accounts' own rows are reachable by no guest, and by no HTTP caller.

    The accounts cannot read them either -- there is no sign-in -- so the honest
    assertion is the one the contract fixes: every guest is refused, with the same
    404 an unknown task gets.
    """
    for guest in ("guest_a", "guest_b"):
        headers = {"X-Guest-Session": GUEST_TOKENS[guest]}

        for victim in USER_TOKENS:
            task_id = accounts[victim]["body"].get("id", "")

            task = await client.get(f"/api/agent/tasks/{task_id}", headers=headers)
            audit = await client.get(f"/api/agent/tasks/{task_id}/audit", headers=headers)

            report.equal(f"D: {guest} cannot read {victim}'s task", task.status_code, 404)
            report.equal(
                f"D: nor {victim}'s audit, and with the same code",
                (audit.status_code, audit.json().get("code")),
                (404, task.json().get("code")),
            )


# --------------------------------------------------------------------------- #
# A -- every guest can reach their own task and audit
# --------------------------------------------------------------------------- #


async def check_owner_access(
    client: httpx.AsyncClient, report: Report, tasks: dict[str, dict[str, Any]]
) -> None:
    for owner in ("guest_a", "guest_b"):
        task_id = tasks[owner]["body"].get("id", "")
        headers = {"X-Guest-Session": GUEST_TOKENS[owner]}

        task = await client.get(f"/api/agent/tasks/{task_id}", headers=headers)
        audit = await client.get(f"/api/agent/tasks/{task_id}/audit", headers=headers)

        report.check(
            f"A: {owner} reads its own task",
            task.status_code == 200 and task.json().get("id") == task_id,
            task.status_code,
        )
        report.check(
            f"A: {owner} reads its own audit",
            audit.status_code == 200 and audit.json().get("taskId") == task_id,
            audit.status_code,
        )

        record = audit.json() if audit.status_code == 200 else {}
        report.check(
            f"A: {owner}'s audit records the run that produced it",
            record.get("status") == "completed"
            and (record.get("understanding") or {}).get("specId") == identity_for(owner)[0],
            {"status": record.get("status")},
        )

        owner_row = await task_owner(task_id)
        report.check(
            f"A: {owner}'s audit belongs to {owner}'s project",
            owner_row is not None
            and owner_row["project_public_id"] == PROJECTS[owner]
            and owner_row["audits"] == 1,
            owner_row,
        )


# --------------------------------------------------------------------------- #
# B, C, D -- what a caller from another owner can reach
# --------------------------------------------------------------------------- #

PROBES: tuple[tuple[str, dict[str, str] | None, dict[str, str] | None], ...] = (
    ("an empty credential (what an unauthenticated caller sends)", None, None),
    ("a foreign guest token in a header", {"X-Guest-Session": GUEST_TOKENS["guest_b"]}, None),
    # The client sends guest_a's session by default, so each probe that is *not*
    # meant to be authenticated says so explicitly with an empty credential --
    # otherwise it would be measuring guest_a reading its own task.
    (
        "a bearer token",
        {"Authorization": "Bearer guest-session-b-token", "X-Guest-Session": ""},
        None,
    ),
    (
        "a foreign guest token in a query parameter",
        {"X-Guest-Session": ""},
        {"guestSession": GUEST_TOKENS["guest_b"]},
    ),
)

ENFORCED_STATUS: dict[str, int] = {
    # Phase 8.5 Step 3: the routes verify a guest session before they read
    # anything, so these are the four answers the same probe gets now.
    "an empty credential (what an unauthenticated caller sends)": 401,
    "a foreign guest token in a header": 404,
    "a bearer token": 401,
    "a foreign guest token in a query parameter": 401,
}
"""What each credential shape must produce: 401 when there is no identity, 404
when there is one and the resource is not its own.  The 404 is deliberate -- it is
the same answer as a resource that does not exist, so it cannot be used to learn
that somebody else's task is real."""


async def probe_all(client: httpx.AsyncClient, url: str) -> dict[str, int]:
    """The same read, attempted with every credential shape the product has."""
    observed: dict[str, int] = {}

    for label, headers, params in PROBES:
        # httpx merges the client's default header into every request, so "no
        # credentials" is sent as an explicitly empty credential: the server treats
        # an empty value exactly as an absent one (same 401), and the probe still
        # exercises the path where nothing verifiable arrives.
        response = await client.get(
            url, headers=headers or {"X-Guest-Session": ""}, params=params
        )
        observed[label] = response.status_code

    return observed


async def check_cross_owner(
    client: httpx.AsyncClient,
    report: Report,
    tasks: dict[str, dict[str, Any]],
    accounts: dict[str, dict[str, Any]],
) -> None:
    """B, C and D: three boundaries, measured rather than assumed.

    There is no credential to *send* as user B or as guest B, because no code in
    this service reads one.  So each probe is the request the frontend actually
    makes -- and every shape of credential the product's own model suggests --
    against a task that belongs to somebody else.
    """
    victim = accounts["user_a"]["body"].get("id", "")
    guest_victim = tasks["guest_a"]["body"].get("id", "")

    for label, task_id, cross in (
        ("B: user B against user A's audit", victim, "user_b"),
        ("B: user B against user A's task", victim, "user_b"),
        ("C: guest B against guest A's audit", guest_victim, "guest_b"),
        ("C: guest B against guest A's task", guest_victim, "guest_b"),
        ("D: guest B against user A's audit", victim, "guest_b"),
        ("D: user B against guest A's audit", guest_victim, "user_b"),
    ):
        suffix = "/audit" if label.endswith("audit") else ""
        observed = await probe_all(client, f"/api/agent/tasks/{task_id}{suffix}")

        report.measured(
            f"{label} (as {cross})",
            observed,
            ENFORCED_STATUS,
        )

    report.finding(
        "RESOLVED in Phase 8.5 Step 3: every route resolves guest -> project and "
        "refuses a task id that is not the caller's.  The historical measurement was "
        "'all four credential shapes answer 200'; the same probe now answers 401 "
        "without an identity and 404 with somebody else's, and the cross-owner reads "
        "above are asserted against those expectations rather than against 200."
    )
    report.finding(
        "Still true and unchanged by design: two registered users own projects and "
        "tasks that no guest can reach (D), and there is no user identity yet -- "
        "sign-in is a later phase, so those rows are reachable by nobody over HTTP."
    )
    report.finding(
        "A task and its audit answer with the same status for the same caller, which "
        "is what makes the audit no easier to reach than the task it belongs to."
    )


# --------------------------------------------------------------------------- #
# E -- missing resources keep their existing meaning
# --------------------------------------------------------------------------- #


async def check_missing(
    client: httpx.AsyncClient, report: Report, tasks: dict[str, dict[str, Any]]
) -> None:
    unknown = await client.get(f"/api/agent/tasks/{uuid.uuid4()}")
    report.equal("E: an unknown task is a 404", unknown.status_code, 404)
    report.equal(
        "E: with the project's task-not-found code", unknown.json().get("code"), "task-not-found"
    )

    unknown_audit = await client.get(f"/api/agent/tasks/{uuid.uuid4()}/audit")
    report.equal("E: an unknown task's audit is a 404", unknown_audit.status_code, 404)
    report.equal(
        "E: with the same code as the task route",
        unknown_audit.json().get("code"),
        unknown.json().get("code"),
    )

    malformed = await client.get("/api/agent/tasks/not-a-uuid/audit")
    report.equal("E: a malformed id is the same 404", malformed.status_code, 404)
    report.equal(
        "E: and never a 422 from path validation", malformed.status_code != 422, True
    )

    # A task that exists with no audit row: the two are different answers.
    task_id = tasks["guest_b"]["body"].get("id", "")

    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM agent_task_audits WHERE task_id = :task"),
            {"task": uuid.UUID(task_id)},
        )

    orphan = await client.get(
        f"/api/agent/tasks/{task_id}/audit",
        headers={"X-Guest-Session": GUEST_TOKENS["guest_b"]},
    )
    report.equal("E: a task without a record is a 404", orphan.status_code, 404)
    report.equal("E: and says which of the two is missing", orphan.json().get("code"), "audit-not-found")
    report.check(
        "E: the task itself is still readable",
        (
            await client.get(
                f"/api/agent/tasks/{task_id}",
                headers={"X-Guest-Session": GUEST_TOKENS["guest_b"]},
            )
        ).status_code
        == 200,
    )

    missing_project = await client.post(
        "/api/projects/prj_does_not_exist/agent/tasks",
        json={
            "projectId": "prj_does_not_exist",
            "specId": identity_for("user_a")[0],
            "specDocument": document_for("user_a"),
            "environmentId": None,
            "prompt": "anything",
            "variables": {},
        },
    )
    # Phase 8.5 Step 3: the project check runs before the create path is entered,
    # so an unknown -- or somebody else's -- project is refused by the contract's
    # project-level code.  The effect is unchanged and still asserted below: the
    # create path is never reached, so nothing is written.
    report.equal("E: an unknown project on create is a 404", missing_project.status_code, 404)
    report.equal(
        "E: with the contract's project-level code",
        missing_project.json().get("code"),
        "project-not-found",
    )
    report.check(
        "E: and nothing was written for it",
        (await owner_rows()).get("prj_does_not_exist") is None,
    )


# --------------------------------------------------------------------------- #
# G -- the invariants that do hold
# --------------------------------------------------------------------------- #


async def check_invariants(report: Report, tasks: dict[str, dict[str, Any]]) -> None:
    owners = await owner_rows()
    report.equal("G: every fixture project exists", len(owners), len(PROJECTS))

    for public_id, row in owners.items():
        report.check(
            f"G: {public_id} has exactly one owner",
            (row["user_id"] is None) != (row["guest_session_id"] is None),
            {"user": row["user_id"], "guest": row["guest_session_id"]},
        )

    report.check(
        "G: the database enforces that invariant",
        await constraint_exists("ck_projects_owner_xor"),
        await constraint_names("projects"),
    )

    for owner, task in tasks.items():
        task_id = task["body"].get("id", "")
        row = await task_owner(task_id)

        report.check(
            f"G: {owner}'s task belongs to {owner} alone",
            row is not None
            and row["project_public_id"] == PROJECTS[owner]
            and (row["user_email"] is not None) == owner.startswith("user")
            and (row["guest_token"] is not None) == owner.startswith("guest"),
            row,
        )

    # The audit carries its own task and nothing else.
    task_id = tasks["guest_a"]["body"].get("id", "")
    record = (await get_json(f"/api/agent/tasks/{task_id}/audit")).get("body") or {}
    others = [
        other["body"].get("id")
        for other in tasks.values()
        if other["body"].get("id") and other["body"]["id"] != task_id
    ]
    report.check(
        "G: an audit names its own task and no other",
        record.get("taskId") == task_id
        and all(other not in json.dumps(record) for other in others),
    )
    report.check(
        "G: and it reaches no further than that task's project",
        (record.get("understanding") or {}).get("specId") == identity_for("guest_a")[0],
    )


async def get_json(url: str, *, token: str = GUEST_TOKENS["guest_a"]) -> dict[str, Any]:
    """One authenticated read, for the invariant checks below."""
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://verify",
        headers={"X-Guest-Session": token},
    ) as client:
        response = await client.get(url)

    return {"status": response.status_code, "body": response.json() if response.content else {}}


async def constraint_exists(name: str) -> bool:
    return name in await constraint_names("projects")


async def constraint_names(table: str) -> list[str]:
    async with AsyncSessionLocal() as session:
        return list(
            (
                await session.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = (:table)::regclass ORDER BY conname"
                    ),
                    {"table": table},
                )
            ).scalars().all()
        )


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


async def main() -> int:
    report = Report()
    await ensure_fixture()

    print("reviewing access control on the agent task and audit routes\n")

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    try:
        # Every request carries guest_a's session unless a probe says otherwise:
        # the fixture's own bootstrap calls are not what this suite is measuring.
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://verify",
            headers={"X-Guest-Session": GUEST_TOKENS["guest_a"]},
        ) as client:
            tasks: dict[str, dict[str, Any]] = {}

            for owner in ("guest_a", "guest_b"):
                tasks[owner] = await create_task(client, owner)

            report.check(
                "F: both guests can create a task in their own project",
                all(tasks[owner]["status"] == 201 for owner in ("guest_a", "guest_b")),
                {owner: tasks[owner]["status"] for owner in ("guest_a", "guest_b")},
            )

            account_tasks = await seed_user_tasks()
            report.check(
                "F: each created task produced a draft plan",
                all(
                    (tasks[owner]["body"].get("plan") or {}).get("status") == "draft"
                    for owner in ("guest_a", "guest_b")
                ),
            )

            await check_owner_access(client, report, tasks)
            await check_user_owned_is_unreachable(client, report, account_tasks)
            await check_cross_owner(client, report, tasks, account_tasks)
            await check_missing(client, report, tasks)
            await check_invariants(report, tasks)
    finally:
        await engine.dispose()
        await cleanup()

    print(f"\n{report.passed} passed, {len(report.failures)} failed")
    print(f"{len(report.measurements)} measurements, {len(report.findings)} findings")

    for failure in report.failures:
        print(f"  - {failure}")

    print("\nfindings (what this review concluded):")
    for index, finding in enumerate(report.findings, start=1):
        print(f"  {index}. {finding}")

    return len(report.failures)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

