"""The smallest project bootstrap the console needs: list mine, create one.

Phase 8.5 Step 3.  Two operations, both scoped to the verified guest that asks:

* list the projects this guest owns -- by `guest_session_id`, never by "all
  projects, filtered later", because a filter the client applies is not a filter;
* create a project whose owner is **the identity the server verified**, never a
  value from the request body.

**Why this exists at all.**  The console's project ids came from a mock list, and
the backend has no project endpoint: a guest could authenticate and then have
nowhere to go.  This is the missing link, deliberately no bigger than that -- no
rename, no delete, no membership, no environment management.

**A project arrives with one environment.**  A run needs an environment id, and
there is no environment API; without one, an authenticated console could create a
project and still not run anything.  The default environment is created in the
same transaction with the base URL the caller supplied (or a loopback default),
and it is returned by the listing so the console can use it.  Managing further
environments is a later step, and this is the smallest honest substitute.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models.project import ApiSpec, Environment, Project
from backend.db.models.user import GuestSession
from backend.schemas.project import (
    EnvironmentVariableResponse,
    ProjectEnvironmentResponse,
    ProjectResponse,
)
from backend.services.spec_identity import slugify

__all__ = ["create_for_guest", "list_for_guest"]

logger = logging.getLogger(__name__)

PROJECT_PREFIX = "prj"
ENVIRONMENT_PREFIX = "env"
DEFAULT_ENVIRONMENT_NAME = "Development"
DEFAULT_ENVIRONMENT_KIND = "development"
DEFAULT_ENVIRONMENT_BASE_URL = "http://127.0.0.1:8000"
"""Where a run would go before the caller says otherwise.

Loopback, because that is where `uv run backend` puts the service this project
tests in development, and because a placeholder that points at somebody's
production is a worse default than one that points at nothing.
"""

_NAME_LIMIT = 200
"""The projects.name column's width."""

_SUFFIX_LENGTH = 8


def project_public_id(name: str) -> str:
    """A stable-looking, unique public id: prj_<slug>_<random suffix>.

    The slug makes it readable in a log line and keeps the console's existing
    shape (prj_orders), and the suffix is what makes it unique without a
    round trip -- two guests may legitimately name their project the same thing.
    """
    slug = slugify(name)[: _NAME_LIMIT - len(PROJECT_PREFIX) - _SUFFIX_LENGTH - 2] or "project"

    return f"{PROJECT_PREFIX}_{slug}_{uuid.uuid4().hex[:_SUFFIX_LENGTH]}"


async def _spec_name(session: AsyncSession, project_id: uuid.UUID) -> str | None:
    """The document this project most recently had parsed, if any."""
    found = await session.execute(
        select(ApiSpec.filename, ApiSpec.name)
        .where(ApiSpec.project_id == project_id)
        .order_by(ApiSpec.created_at.desc())
        .limit(1)
    )
    row = found.one_or_none()

    if row is None:
        return None

    return row[0] or row[1]


async def _environments(
    session: AsyncSession, project_id: uuid.UUID
) -> list[ProjectEnvironmentResponse]:
    found = await session.execute(
        select(Environment)
        .where(Environment.project_id == project_id)
        .order_by(Environment.created_at)
    )

    return [
        ProjectEnvironmentResponse(
            id=environment.public_id,
            name=environment.name,
            kind=environment.kind,
            base_url=environment.base_url,
            # Variables are not read here on purpose: this response is about the
            # project, and the console has no screen that shows a value.
            variables=[],
        )
        for environment in found.scalars().all()
    ]


async def _response(session: AsyncSession, project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.public_id,
        name=project.name,
        description=project.description or "",
        spec_name=await _spec_name(session, project.id),
        environments=await _environments(session, project.id),
        updated_at=project.updated_at,
    )


async def list_for_guest(session: AsyncSession, *, guest: GuestSession) -> list[ProjectResponse]:
    """Every project this guest owns, and nothing else.

    The WHERE clause is the authorization: there is no path here that reads a
    project owned by another guest or by a registered user, so no response can
    leak one.
    """
    found = await session.execute(
        select(Project)
        .where(Project.guest_session_id == guest.id)
        .order_by(Project.created_at)
    )

    return [await _response(session, project) for project in found.scalars().all()]


async def create_for_guest(
    session: AsyncSession,
    *,
    guest: GuestSession,
    name: str,
    base_url: str | None = None,
) -> ProjectResponse:
    """Create a project owned by the verified guest, with one environment.

    Ownership is not a parameter: it is the identity the request arrived with, so
    a body that claims somebody else's session cannot be honoured even if a caller
    works out the field name.
    """
    project = Project(
        public_id=project_public_id(name),
        name=name.strip()[:_NAME_LIMIT],
        description=None,
        guest_session_id=guest.id,
        user_id=None,
    )
    session.add(project)
    await session.flush()

    environment = Environment(
        project_id=project.id,
        public_id=f"{ENVIRONMENT_PREFIX}_{project.public_id}",
        name=DEFAULT_ENVIRONMENT_NAME,
        kind=DEFAULT_ENVIRONMENT_KIND,
        base_url=(base_url or DEFAULT_ENVIRONMENT_BASE_URL).strip(),
        is_default=True,
    )
    session.add(environment)
    await session.flush()

    logger.info("created project %s for guest %s", project.public_id, guest.id)

    return await _response(session, project)
