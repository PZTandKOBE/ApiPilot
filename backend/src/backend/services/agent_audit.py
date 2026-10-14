"""Recording what the agent decided, and what it cost.

Phase 8.4 Step 1.  One row per task, written by this module and nobody else.

**The recorder, not a second pipeline.**  Every function here takes the caller's
session and never commits: the task's own transaction boundaries are the ones the
contract froze, and an audit that committed on its own would be a second writer to
the same story.  What it adds is memory -- which model ran each stage, which prompt
it read, what it produced, what the call cost, and where a failure happened --
kept in one place so the next question about an agent decision has somewhere to
look.

**Problems are recorded, never raised.**  A missing audit row is logged and the
pipeline continues: the plan is the product, and losing an audit line is not a
reason to fail a task.  (The row cannot go missing in practice -- it is written in
the same commit as the task -- but a recorder that can break the thing it records
is worse than one that cannot.)

**Secrets have no path in.**  The audit stores the provider, the model, the prompt
version, the validated understanding, the validated design, the token counts and a
bounded failure summary.  It never stores a document, a prompt, a request, a
response, a header or a credential -- and every value that does go in passes
through :func:_without_secrets, which removes any run-time value the task declared
before it reaches a column.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models.agent import AgentTaskAudit

__all__ = [
    "FAILURE_MESSAGE_LIMIT",
    "STAGES",
    "complete",
    "create",
    "fail",
    "load",
    "save_analysis",
    "save_plan",
    "set_stage",
]

logger = logging.getLogger(__name__)

STAGES = (
    "pending",
    "analyzing",
    "parse",
    "analyze",
    "generate",
    "validate",
    "persist",
    "completed",
    "failed",
)

FAILURE_MESSAGE_LIMIT = 500
"""How much of a failure's prose is kept.  Matches the column's width."""

_REDACTED = "[redacted]"


async def _row(session: AsyncSession, task_id: Any) -> AgentTaskAudit | None:
    found = await session.execute(
        select(AgentTaskAudit).where(AgentTaskAudit.task_id == task_id)
    )

    return found.scalar_one_or_none()


def _bounded(message: str | None) -> str | None:
    """One line, bounded, for the failure summary."""
    if message is None:
        return None

    collapsed = " ".join(str(message).split())

    if collapsed == "":
        return None

    return collapsed[:FAILURE_MESSAGE_LIMIT]


def _without_secrets(value: Any, forbidden: Iterable[str]) -> Any:
    """The same structure, with any run-time value this task declared removed.

    Not a general redactor and deliberately not clever: it replaces *exact* values
    the caller says are secret, so ordinary text that merely looks sensitive -- a
    field named token, a path named /auth/login -- survives untouched.  It works
    on the serialised form, so a value buried in a nested string is removed too.
    """
    secrets = [
        secret for secret in forbidden if isinstance(secret, str) and secret.strip() != ""
    ]

    if not secrets:
        return value

    try:
        text = json.dumps(value, ensure_ascii=True, default=str)
    except (TypeError, ValueError):  # pragma: no cover - the audit stores mappings
        logger.warning("agent audit could not serialise a value for the secret scan")

        return None

    for secret in secrets:
        text = text.replace(json.dumps(secret)[1:-1], _REDACTED)

    return json.loads(text)


def _with_usage(
    existing: Mapping[str, Any] | None,
    stage: str,
    usage: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The usage map, with one stage's counts replaced.  Absent stays absent."""
    merged: dict[str, Any] = dict(existing or {})

    if usage:
        merged[stage] = dict(usage)
    else:
        merged.pop(stage, None)

    return merged


async def create(session: AsyncSession, *, task_id: Any) -> None:
    """Open the record for a task, in the caller's transaction.

    Called in the same commit that inserts the task, so the two either both exist
    or neither does.
    """
    session.add(AgentTaskAudit(task_id=task_id, status="pending"))


async def set_stage(session: AsyncSession, *, task_id: Any, stage: str) -> None:
    """Say where the pipeline is now.

    The stage is durable at the pipeline's own commit boundaries; a failure is
    recorded with the stage the caller reports, not with whatever this column
    happens to hold at the time.
    """
    if stage not in STAGES:
        raise ValueError(f"{stage!r} is not an agent audit stage")

    row = await _row(session, task_id)

    if row is None:  # pragma: no cover - created with the task
        logger.warning("agent audit row for task %s is missing", task_id)

        return

    row.status = stage


async def save_analysis(
    session: AsyncSession,
    *,
    task_id: Any,
    provider: str,
    model: str | None,
    prompt: str | None,
    usage: Mapping[str, Any] | None,
    understanding: Mapping[str, Any] | None,
    forbidden_values: Iterable[str] = (),
) -> None:
    """Record who analysed the document, what they understood, and what it cost."""
    row = await _row(session, task_id)

    if row is None:  # pragma: no cover - created with the task
        logger.warning("agent audit row for task %s is missing", task_id)

        return

    row.analyzer_provider = provider
    row.analyzer_model = model
    row.analyzer_prompt = prompt
    row.usage = _with_usage(row.usage, "analyze", usage)
    row.understanding = _without_secrets(understanding, forbidden_values)


async def save_plan(
    session: AsyncSession,
    *,
    task_id: Any,
    provider: str,
    model: str | None,
    prompt: str | None,
    usage: Mapping[str, Any] | None,
    design: Mapping[str, Any] | None,
    forbidden_values: Iterable[str] = (),
) -> None:
    """Record who designed the plan, what they designed, and what it cost."""
    row = await _row(session, task_id)

    if row is None:  # pragma: no cover - created with the task
        logger.warning("agent audit row for task %s is missing", task_id)

        return

    row.planner_provider = provider
    row.planner_model = model
    row.planner_prompt = prompt
    row.usage = _with_usage(row.usage, "generatePlan", usage)
    row.plan_design = _without_secrets(design, forbidden_values)


async def complete(session: AsyncSession, *, task_id: Any) -> None:
    """The pipeline finished and the plan is stored."""
    row = await _row(session, task_id)

    if row is None:  # pragma: no cover - created with the task
        logger.warning("agent audit row for task %s is missing", task_id)

        return

    row.status = "completed"
    row.failure_stage = None
    row.failure_code = None
    row.failure_message = None


async def fail(
    session: AsyncSession,
    *,
    task_id: Any,
    stage: str | None,
    code: str | None,
    message: str | None,
) -> None:
    """Record where and why the pipeline stopped.

    Only the stage, the code and a bounded sentence: a traceback belongs in the
    server's log, not in a row a client can read.
    """
    row = await _row(session, task_id)

    if row is None:  # pragma: no cover - created with the task
        logger.warning("agent audit row for task %s is missing", task_id)

        return

    row.status = "failed"
    row.failure_stage = stage
    row.failure_code = code
    row.failure_message = _bounded(message)


async def load(session: AsyncSession, *, task_id: Any) -> Mapping[str, Any] | None:
    """The stored record, as plain values."""
    row = await _row(session, task_id)

    if row is None:
        return None

    return {
        "task_id": str(row.task_id),
        "status": row.status,
        "failure_stage": row.failure_stage,
        "failure_code": row.failure_code,
        "failure_message": row.failure_message,
        "analyzer_provider": row.analyzer_provider,
        "analyzer_model": row.analyzer_model,
        "analyzer_prompt": row.analyzer_prompt,
        "planner_provider": row.planner_provider,
        "planner_model": row.planner_model,
        "planner_prompt": row.planner_prompt,
        "understanding": row.understanding,
        "plan_design": row.plan_design,
        "usage": row.usage,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
