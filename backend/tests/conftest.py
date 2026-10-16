"""Test bootstrap for the backend.

Three rules hold for everything in this directory.

**The scratch database is chosen before any backend.* import.**  database_url and
AsyncSessionLocal are module-level objects built at import time, so there is no later
moment at which the target could be changed.  Setting the variable here -- and failing
loudly if the resolved name is not what we expect -- is the whole isolation mechanism.
python -O strips assert, so the check raises instead.

**Every phase gets its own session.**  Fixtures are written in one session and read
back in a second one, freshly opened.  The recovery code commits in a transaction of
its own, and a session that had already started a transaction would not see that
commit -- reading through a new session removes the question instead of reasoning
about snapshot boundaries.  Teardown likewise opens its own session, so cleanup
happens even when a test failed with its session mid-transaction.

**Nothing here reads a credential.**  load_dotenv runs inside backend.db.database at
import, exactly as in production; this file never touches DEEPSEEK_API_KEY and never
prints a connection string.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# 1. Choose the database BEFORE importing anything from backend.
# --------------------------------------------------------------------------- #

SCRATCH_DB = "aiata_c4_test"

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
if _ENV_FILE.is_file():
    from dotenv import load_dotenv

    # Does not override variables that are already set, which is why the line
    # below wins over anything in the developer .env.
    load_dotenv(_ENV_FILE)

os.environ["POSTGRES_DB"] = SCRATCH_DB

# --------------------------------------------------------------------------- #
# 2. Import the application objects, then prove where they point.
# --------------------------------------------------------------------------- #

import pytest  # noqa: E402
from sqlalchemy import delete, select, text  # noqa: E402

from backend.db import database  # noqa: E402
from backend.db.models.agent import TestPlan  # noqa: E402
from backend.db.models.project import ApiSpec, Project  # noqa: E402
from backend.db.models.result import RunEvent, TestRun  # noqa: E402
from backend.db.models.user import GuestSession  # noqa: E402


def _refuse(message: str) -> None:
    """Fail the run, not an assertion: python -O must not be able to skip this."""
    raise RuntimeError(message)


if database.database_url.database != SCRATCH_DB:
    _refuse(
        "refusing to run: the resolved database is "
        f"{database.database_url.database!r}, expected {SCRATCH_DB!r}"
    )


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Only asyncio.

    The built-in fixture is parametrised over every available backend, which would run
    the whole file twice the moment anything installs trio.  The engine is bound to the
    loop that first uses it, so one backend is also the honest number.
    """
    return "asyncio"


@pytest.fixture(scope="session")
async def engine():
    """The one engine, disposed at the end of the session.

    Every test in the session shares an event loop (that is how the anyio plugin runs
    them), so pooled connections stay valid throughout.
    """
    yield database.engine
    await database.engine.dispose()


@asynccontextmanager
async def _opened_session(engine):
    """A plain session, opened and closed where it is used."""
    async with database.AsyncSessionLocal() as opened:
        yield opened


@pytest.fixture
async def write_session(engine):
    """Builds fixtures.  Committed by the fixture helpers, never left dirty."""
    async with _opened_session(engine) as session:
        yield session
        await session.rollback()


@pytest.fixture
async def read_session(engine):
    """Reads what the code under test committed, in a transaction of its own."""
    async with _opened_session(engine) as session:
        yield session
        await session.rollback()


class _Fixtures:
    """Creates one project's worth of rows per test, and remembers what it made.

    Ids are new on every call, so nothing here can collide with development data even
    if the two ever shared a database.  Cleanup deletes exactly these ids and nothing
    else -- no TRUNCATE, no table-wide DELETE.
    """

    def __init__(self, session) -> None:
        self.session = session
        self.created: list[tuple[type, uuid.UUID]] = []
        self._tag = uuid.uuid4().hex[:12]

    async def _keep(self, model, row) -> uuid.UUID:
        """Flush, remember the id for cleanup, and hand back only the id.

        Ids and not instances: an ORM object can be expired by a later commit or
        rollback, and reading a plain UUID never touches the database.
        """
        await self.session.flush()
        row_id = row.id
        self.created.append((model, row_id))
        return row_id

    # -- identity ---------------------------------------------------------- #

    async def guest(self) -> uuid.UUID:
        row = GuestSession(
            token_hash=("c4" + uuid.uuid4().hex + uuid.uuid4().hex)[:64],
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            last_seen_at=datetime.now(timezone.utc),
        )
        self.session.add(row)
        return await self._keep(GuestSession, row)

    async def project(self, guest_id: uuid.UUID) -> uuid.UUID:
        row = Project(
            guest_session_id=guest_id,
            public_id=f"c4prj_{self._tag}_{uuid.uuid4().hex[:8]}",
            name="C4 scratch project",
            description="Created by backend/tests; deleted by its own cleanup.",
        )
        self.session.add(row)
        return await self._keep(Project, row)

    async def spec(self, project_id: uuid.UUID) -> uuid.UUID:
        row = ApiSpec(
            project_id=project_id,
            name="C4 scratch spec",
            slug=f"c4spec_{self._tag}",
            spec_type="openapi-3",
            content_format="json",
            content='{"openapi": "3.0.0", "info": {"title": "c4", "version": "1"}}',
        )
        self.session.add(row)
        return await self._keep(ApiSpec, row)

    async def plan(self, project_id: uuid.UUID, spec_id: uuid.UUID) -> uuid.UUID:
        row = TestPlan(
            project_id=project_id,
            spec_id=spec_id,
            public_id=f"c4plan_{self._tag}_{uuid.uuid4().hex[:8]}",
            name={"text": "C4 scratch plan"},
            description={"text": "Created by backend/tests."},
            status="approved",
            risk_level="low",
            source="human",
            approved_at=datetime.now(timezone.utc),
        )
        self.session.add(row)
        return await self._keep(TestPlan, row)

    # -- test_runs --------------------------------------------------------- #

    async def run(
        self,
        stack,
        *,
        status: str = "queued",
        started_at: datetime | None = None,
    ) -> uuid.UUID:
        """A queued (or running) run for the fixture stack; returns its id."""
        row = TestRun(
            project_id=stack["project"],
            plan_id=stack["plan"],
            spec_id=stack["spec"],
            environment_id=None,
            plan_name={"text": "C4 scratch plan"},
            base_url="http://127.0.0.1:9/c4-never-called",
            status=status,
            started_at=started_at,
        )
        self.session.add(row)
        return await self._keep(TestRun, row)

    async def backdate_run(self, run_id: uuid.UUID, seconds: int) -> None:
        """Move created_at into the past with SQL, never by sleeping.

        Raw SQL because created_at is a server default with no ORM setter -- the same
        reason the recovery code reads the age from the database clock.
        """
        await self.session.execute(
            text(
                "UPDATE test_runs SET created_at = now() - make_interval(secs => :s) "
                "WHERE id = :i"
            ),
            {"s": seconds, "i": run_id},
        )

    async def started_event(self, run_id: uuid.UUID) -> None:
        """A run.started row, written the way the executor writes one."""
        self.session.add(
            RunEvent(
                run_id=run_id,
                seq=1,
                event_type="run.started",
                payload={"startedAt": datetime.now(timezone.utc).isoformat()},
            )
        )

    async def commit(self) -> None:
        """Make the fixture visible to every other connection."""
        await self.session.commit()

    # -- reading back ------------------------------------------------------ #

    @staticmethod
    async def events(session, run_id: uuid.UUID) -> list[RunEvent]:
        result = await session.execute(
            select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
        )
        return list(result.scalars())

    @staticmethod
    async def reload(session, run_id: uuid.UUID) -> TestRun:
        return (
            await session.execute(select(TestRun).where(TestRun.id == run_id))
        ).scalar_one()

    @staticmethod
    async def count_events(session) -> int:
        result = await session.execute(select(RunEvent.id))
        return len(list(result.scalars()))

    async def cleanup(self, engine) -> None:
        """Delete the ids this fixture made, children first, in its own session.

        run_events / run_scenarios / run_steps / run_assertions are ON DELETE CASCADE
        from test_runs, so removing the run row is enough for them; the events are
        deleted explicitly anyway so the intent is visible.  Its own session and its
        own commit mean cleanup still happens when the test failed mid-transaction.
        """
        if not self.created:
            return
        async with database.AsyncSessionLocal() as session:
            for model, row_id in reversed(self.created):
                if model is TestRun:
                    await session.execute(
                        delete(RunEvent).where(RunEvent.run_id == row_id)
                    )
                await session.execute(delete(model).where(model.id == row_id))
            await session.commit()
        self.created.clear()


@pytest.fixture
async def fixtures(write_session, engine):
    """Fixture factory with guaranteed cleanup, even when the test fails."""
    built = _Fixtures(write_session)
    try:
        yield built
    finally:
        await built.cleanup(engine)


@pytest.fixture
async def stack(fixtures):
    """The whole required chain -- guest, project, spec, plan -- committed."""
    guest = await fixtures.guest()
    project = await fixtures.project(guest)
    spec = await fixtures.spec(project)
    plan = await fixtures.plan(project, spec)
    await fixtures.commit()
    """The required chain as plain ids -- guest, project, spec, plan -- committed."""
    return {"guest": guest, "project": project, "spec": spec, "plan": plan}
