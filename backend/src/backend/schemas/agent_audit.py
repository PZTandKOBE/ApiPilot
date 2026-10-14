"""Agent task audit schemas.

Phase 8.4 Step 1.  The read side of `agent_task_audits`: what the pipeline
recorded about one task's decisions.

The shape answers four questions and refuses to answer any others: who ran the
analysis and the design (provider, model, prompt version), what they produced
(the validated understanding and the validated design), what it cost (the counts
the provider reported, per stage), and -- when it went wrong -- where and why.
It carries no document, no prompt text, no header and no credential, because the
table does not.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from backend.schemas.base import Schema

__all__ = [
    "AgentAuditStageResponse",
    "AgentTaskAuditResponse",
    "AgentUsageCounts",
    "AgentUsageResponse",
]


class AgentAuditStageResponse(Schema):
    """Who ran one stage, with which model and which prompt."""

    provider: str | None = Field(
        default=None,
        description=(
            "deepseek when this stage called the model, deterministic when the rule "
            "engine ran it, null when the pipeline stopped before this stage. Read "
            "from the run itself, never assumed from the current configuration."
        ),
    )
    model: str | None = Field(
        default=None,
        description="The model this stage asked for; null when no model ran.",
    )
    prompt_version: str | None = Field(
        default=None,
        description=(
            "The versioned prompt asset this stage read -- analyze-v1 or "
            "generate-plan-v1; null when no prompt was read."
        ),
    )


class AgentUsageCounts(Schema):
    """The token counts one stage's provider reported.

    Only the counts that came back.  A provider that reports four of the five
    leaves one null, and a stage that called no model has no object at all --
    zeroes would make "no model ran" and "the model charged nothing" the same
    answer.
    """

    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None


class AgentUsageResponse(Schema):
    """What each model call cost, kept apart by stage."""

    analyze: AgentUsageCounts | None = None
    generate_plan: AgentUsageCounts | None = None


class AgentTaskAuditResponse(Schema):
    """One task's audit record."""

    task_id: str
    status: str = Field(
        description=(
            "The stage the audit last recorded: pending, analyzing, parse, analyze, "
            "generate, validate, persist, completed or failed."
        )
    )
    failure_stage: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    analyzer: AgentAuditStageResponse
    planner: AgentAuditStageResponse
    understanding: dict[str, Any] | None = Field(
        default=None,
        description="The validated understanding, as the analysis stage produced it.",
    )
    plan_design: dict[str, Any] | None = Field(
        default=None,
        description=(
            "The validated design, before the runtime completed it into the stored "
            "plan. Null when the rule engine designed the plan, because it produces "
            "the contract directly and has no separate design."
        ),
    )
    usage: AgentUsageResponse
    created_at: datetime
    updated_at: datetime
