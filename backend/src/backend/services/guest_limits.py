"""Server-side limits for the official-cloud guest experience.

The browser guest identity is deliberately separate from an account, but it
still writes projects, runs and agent tasks. The limits here are enforced in
the service layer before a write, not in the browser, and they need no new
database table: the existing ownership foreign keys already answer every count.

Only browser guests in official cloud are limited. self_hosted keeps its
original unlimited guest behavior, and an account's internal guest bridges a
registered user_id rather than a browser guest.
"""

from __future__ import annotations

from datetime import datetime, time, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import AppError
from backend.db.models.agent import AgentTask
from backend.db.models.project import Project
from backend.db.models.result import TestRun
from backend.db.models.user import GuestSession
from backend.services.auth_config import AuthSettings

__all__ = [
    "enforce_agent_task_limit",
    "enforce_project_limit",
    "enforce_run_limit",
]

GUEST_LIMIT_CODE = "guest-limit-reached"
_GUEST_LIMIT_MESSAGE_KEY = "auth.errors.guestLimitReached"


def _is_limited_guest(settings: AuthSettings, guest: GuestSession) -> bool:
    return settings.official_cloud and guest.user_id is None


def _exceeded(scope: str, limit: int) -> AppError:
    return AppError(
        429,
        code=GUEST_LIMIT_CODE,
        message_key=_GUEST_LIMIT_MESSAGE_KEY,
        details={"scope": scope, "limit": limit},
    )


async def _count_projects(session: AsyncSession, guest: GuestSession) -> int:
    found = await session.execute(
        select(func.count(Project.id)).where(Project.guest_session_id == guest.id)
    )
    return int(found.scalar_one())


async def _count_runs(session: AsyncSession, guest: GuestSession) -> int:
    found = await session.execute(
        select(func.count(TestRun.id))
        .select_from(TestRun)
        .join(Project, Project.id == TestRun.project_id)
        .where(Project.guest_session_id == guest.id)
    )
    return int(found.scalar_one())


async def _count_agent_tasks(session: AsyncSession, guest: GuestSession) -> int:
    found = await session.execute(
        select(func.count(AgentTask.id))
        .select_from(AgentTask)
        .join(Project, Project.id == AgentTask.project_id)
        .where(Project.guest_session_id == guest.id)
    )
    return int(found.scalar_one())


async def _count_daily_official_guest_tasks(session: AsyncSession) -> int:
    start = datetime.combine(
        datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc
    )
    found = await session.execute(
        select(func.count(AgentTask.id))
        .select_from(AgentTask)
        .join(Project, Project.id == AgentTask.project_id)
        .join(GuestSession, GuestSession.id == Project.guest_session_id)
        .where(
            GuestSession.user_id.is_(None),
            AgentTask.created_at >= start,
        )
    )
    return int(found.scalar_one())


async def enforce_project_limit(
    session: AsyncSession, *, guest: GuestSession, settings: AuthSettings
) -> None:
    if not _is_limited_guest(settings, guest):
        return
    if await _count_projects(session, guest) >= settings.official_guest_max_projects:
        raise _exceeded("projects", settings.official_guest_max_projects)


async def enforce_run_limit(
    session: AsyncSession, *, guest: GuestSession, settings: AuthSettings
) -> None:
    if not _is_limited_guest(settings, guest):
        return
    if await _count_runs(session, guest) >= settings.official_guest_max_runs:
        raise _exceeded("runs", settings.official_guest_max_runs)


async def enforce_agent_task_limit(
    session: AsyncSession, *, guest: GuestSession, settings: AuthSettings
) -> None:
    if not _is_limited_guest(settings, guest):
        return

    if (
        await _count_agent_tasks(session, guest)
        >= settings.official_guest_max_agent_tasks
    ):
        raise _exceeded("agent-tasks", settings.official_guest_max_agent_tasks)

    if (
        await _count_daily_official_guest_tasks(session)
        >= settings.official_guest_daily_agent_tasks
    ):
        raise _exceeded("daily-agent-tasks", settings.official_guest_daily_agent_tasks)
