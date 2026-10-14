"""Development seed data.  Not a migration, and not part of the service.

The database has no way to create a project, an environment or a guest session
through the API yet -- there is no Project CRUD, no Environment CRUD and no
auth -- so ``POST /api/projects/{project_id}/runs`` cannot be exercised against
a real row at all until something puts one there.  This script is that
something, and it is deliberately outside the application: no router imports it,
no startup hook runs it, and deleting it changes nothing about how the service
behaves.

The ids are the ones the frontend already uses (``frontend/src/services/mock/
projects.ts``), so a request the browser would actually build resolves here
without edits.  ``prj_orders`` and ``env_orders_staging`` in particular.

``projects.owner_xor`` requires an owner, and there are no users, so every
project hangs off a guest session.  That ordering is not optional: the
constraint is checked per statement, so the session row has to exist first.

Idempotent.  Run it twice and the second run reports everything as already
present and writes nothing.

    python scripts/seed_dev_data.py
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:  # installed package (uv_build src-layout); fall back for a bare checkout
    import backend  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on how it is invoked
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from backend.db.database import AsyncSessionLocal  # noqa: E402
from backend.db.models.project import Environment, EnvironmentVariable, Project  # noqa: E402
from backend.db.models.user import GuestSession  # noqa: E402

__all__ = ["main", "seed"]

GUEST_TOKEN = "dev-guest-session"

PROJECT = {
    "public_id": "prj_orders",
    "name": "My Project",
    "description": "Order lifecycle API behind the checkout flow.",
}

# (public_id, name, kind, base_url, is_default, variables)
# `is_default` is set on Staging rather than Development so it matches the
# environment the checks below run against, and because
# `uq_environments_one_default` allows exactly one.
ENVIRONMENTS = [
    (
        "env_orders_dev",
        "Development",
        "development",
        "https://api.dev.example.com",
        False,
        [
            ("baseUrl", "https://api.dev.example.com", False),
            ("token", "dev_2f9c41ab7e", True),
            ("order_id", "order_001", False),
        ],
    ),
    (
        "env_orders_staging",
        "Staging",
        "staging",
        "https://api.stg.example.com",
        True,
        [
            ("baseUrl", "https://api.stg.example.com", False),
            ("token", "stg_88d0fe13c4", True),
            ("order_id", "order_90021", False),
        ],
    ),
    (
        "env_orders_prod",
        "Production",
        "production",
        "https://api.example.com",
        False,
        [
            ("baseUrl", "https://api.example.com", False),
            ("token", "prod_5ba71c90", True),
        ],
    ),
]


def _guest_digest() -> str:
    """The digest the service would store for this fixture's token.

    The development seed names a token, and the schema only remembers digests
    (Phase 8.5 Step 2) -- so the seed hashes exactly as the service does, and
    the token it prints is the one a browser would have to present.
    """
    return hashlib.sha256(GUEST_TOKEN.encode("utf-8")).hexdigest()


async def _guest_session(session: AsyncSession) -> tuple[GuestSession, bool]:
    existing = (
        await session.execute(
            select(GuestSession).where(
                GuestSession.token_hash == _guest_digest()
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        return existing, False

    created = GuestSession(
        token_hash=_guest_digest(),
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        last_seen_at=datetime.now(timezone.utc),
    )
    session.add(created)
    await session.flush()
    return created, True


async def _project(session: AsyncSession, guest: GuestSession) -> tuple[Project, bool]:
    existing = (
        await session.execute(
            select(Project).where(Project.public_id == PROJECT["public_id"])
        )
    ).scalar_one_or_none()

    if existing is not None:
        return existing, False

    created = Project(
        # user_id stays NULL -- `owner_xor` forbids both owners at once, not
        # neither, and a guest session is the only owner that exists here.
        guest_session_id=guest.id,
        public_id=PROJECT["public_id"],
        name=PROJECT["name"],
        description=PROJECT["description"],
    )
    session.add(created)
    await session.flush()
    return created, True


async def _environment(
    session: AsyncSession, project: Project, spec: tuple
) -> tuple[Environment, bool]:
    public_id, name, kind, base_url, is_default, _variables = spec

    existing = (
        await session.execute(
            select(Environment).where(
                Environment.project_id == project.id, Environment.public_id == public_id
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        return existing, False

    created = Environment(
        project_id=project.id,
        public_id=public_id,
        name=name,
        kind=kind,
        base_url=base_url,
        is_default=is_default,
    )
    session.add(created)
    await session.flush()
    return created, True


async def _variable(
    session: AsyncSession, environment: Environment, spec: tuple[str, str, bool]
) -> bool:
    key, value, is_secret = spec

    existing = (
        await session.execute(
            select(EnvironmentVariable).where(
                EnvironmentVariable.environment_id == environment.id,
                EnvironmentVariable.key == key,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        return False

    session.add(
        EnvironmentVariable(
            environment_id=environment.id,
            key=key,
            # Not encrypted, and that is stated rather than implied: the column
            # is the application layer's to fill and the application layer has
            # no key management yet.  This is development data on a local
            # database.  Nothing in this repository reads it back.
            value_encrypted=value,
            is_secret=is_secret,
        )
    )
    await session.flush()
    return True


async def seed(session: AsyncSession) -> dict[str, int]:
    """Write the seed data, skipping anything already present."""
    counts = {"guest_sessions": 0, "projects": 0, "environments": 0, "variables": 0}

    guest, created = await _guest_session(session)
    counts["guest_sessions"] += int(created)

    project, created = await _project(session, guest)
    counts["projects"] += int(created)

    for spec in ENVIRONMENTS:
        environment, created = await _environment(session, project, spec)
        counts["environments"] += int(created)
        for variable in spec[5]:
            counts["variables"] += int(await _variable(session, environment, variable))

    await session.commit()
    return counts


async def main() -> None:
    async with AsyncSessionLocal() as session:
        counts = await seed(session)

    total = sum(counts.values())
    if total == 0:
        print("seed: everything already present, nothing written")
    else:
        print("seed: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    print(f"seed: project {PROJECT['public_id']!r}, environments "
          f"{', '.join(spec[0] for spec in ENVIRONMENTS)}")


if __name__ == "__main__":
    asyncio.run(main())
