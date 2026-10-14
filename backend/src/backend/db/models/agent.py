"""Agent system: the test plan side of the product.

What a plan *is*, as opposed to what a run *did*.  The distinction is the reason
``test_scenarios`` / ``test_steps`` / ``test_assertions`` exist separately from the ``run_*`` tables that record executions of them.

Two fields deserve a note before the code:

``test_steps`` describes a *test-plan operation*, not an HTTP request.
    It carries ``endpoint_id`` and a ``config`` blob; it does not carry headers,
    a body or an auth scheme.  Composing the actual request from the endpoint is
    the execution engine's job, and giving a step those fields would move the
    frontend into the execution path.

``depends_on`` is a JSONB list of step keys, by design.
    It is a document-ordered reference the database cannot police: nothing
    stops it naming a step from another scenario, or one that sorts later, or
    one that has since been deleted.  Existence and acyclicity are service-layer
    invariants.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from backend.db.models.project import ApiEndpoint, ApiSpec, Environment, Project
    from backend.db.models.result import (
        RunAssertion,
        RunScenario,
        RunStep,
        TestRun,
    )

__all__ = [
    "AgentTask",
    "AgentTaskAudit",
    "TestAssertion",
    "TestPlan",
    "TestScenario",
    "TestStep",
]


class AgentTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One request for the agent to analyse a spec and design tests."""

    __tablename__ = "agent_tasks"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    spec_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        # NO ACTION: an agent task is anchored to the exact document it read.
        # CASCADE would let deleting a spec erase the plans and runs derived
        # from it; RESTRICT would be checked mid-cascade and can fail a project
        # delete whose own cascade has not yet removed these rows.  NO ACTION is
        # deferred to the end of the statement, which is the behaviour we want
        # on both paths.
        ForeignKey("api_specs.id", ondelete="NO ACTION"),
        nullable=False,
        index=True,
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("environments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default=text("'pending'")
    )

    project: Mapped[Project] = relationship("Project", back_populates="agent_tasks", lazy="raise")
    spec: Mapped[ApiSpec] = relationship("ApiSpec", back_populates="agent_tasks", lazy="raise")
    environment: Mapped[Environment | None] = relationship(
        "Environment", back_populates="agent_tasks", lazy="joined"
    )
    test_plans: Mapped[list[TestPlan]] = relationship(
        "TestPlan", back_populates="agent_task", lazy="raise", passive_deletes=True
    )


class AgentTaskAudit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What one agent task decided, and what it cost.

    One row per task, and one task per row: this step records a pipeline run,
    not a retry history, so @@task_id@@ is unique.  When retries arrive they will
    need an attempt column, and this constraint is the thing that will have to
    change -- deliberately left until there is a retry to model.

    The row exists from the moment the task does (the same commit creates both),
    so a task that fails early still has somewhere to say where it failed.  What
    it holds is metadata about decisions -- which model, which prompt, what the
    model understood, what it designed, what the call cost -- and never what the
    pipeline is forbidden to keep: it stores no document, no prompt text, no
    request or response body, no header and no credential.

    @@usage@@ is JSONB rather than sixteen columns because the provider's shape
    is not ours to freeze: the audit stores the counts DeepSeek actually
    reported, under @@analyze@@ and @@generatePlan@@, and a deterministic run
    stores nothing at all rather than a row of zeroes.
    """

    __tablename__ = "agent_task_audits"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default=text("'pending'")
    )
    failure_stage: Mapped[str | None] = mapped_column(String(30), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Bounded on purpose: an exception's prose is not an audit trail, and an
    # unbounded column is how a stack trace ends up in a database.
    failure_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    analyzer_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    analyzer_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    analyzer_prompt: Mapped[str | None] = mapped_column(String(100), nullable=True)
    planner_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    planner_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    planner_prompt: Mapped[str | None] = mapped_column(String(100), nullable=True)

    understanding: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    plan_design: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class TestPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """How the API *should* be tested.

    This is the plan side of the plan/run split.  Editing or deleting a plan
    must not rewrite what an earlier run reported, which is why
    ``test_runs.plan_id`` is ``NO ACTION`` and why deletion here is soft:
    ``deleted_at`` retires a plan without breaking the runs that name it.

    ``name`` and ``description`` are ``LocalizedText`` on the frontend -- the
    authored copy is an i18n key, or a literal when the user renamed the plan --
    so both are JSONB rather than text.

    ``public_id`` (``plan_orders_1a2b3c4d``) is scoped to the project.  It is
    derived from the spec's slug, and the spec is already project-scoped, so a
    project-scoped constraint is the tightest one that is also true.
    """

    __tablename__ = "test_plans"
    __table_args__ = (
        UniqueConstraint("project_id", "public_id", name="uq_test_plans_project_public_id"),
    )

    agent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    spec_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_specs.id", ondelete="NO ACTION"),
        nullable=False,
        index=True,
    )
    public_id: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    name: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    description: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft", server_default=text("'draft'")
    )
    risk_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="medium", server_default=text("'medium'")
    )
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="generated", server_default=text("'generated'")
    )
    approved_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    agent_task: Mapped[AgentTask | None] = relationship(
        "AgentTask", back_populates="test_plans", lazy="joined"
    )
    project: Mapped[Project] = relationship("Project", back_populates="test_plans", lazy="raise")
    spec: Mapped[ApiSpec] = relationship("ApiSpec", back_populates="test_plans", lazy="raise")
    scenarios: Mapped[list[TestScenario]] = relationship(
        "TestScenario", back_populates="plan", lazy="raise", passive_deletes=True
    )
    test_runs: Mapped[list[TestRun]] = relationship(
        "TestRun", back_populates="plan", lazy="raise", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<TestPlan id={self.id!r} status={self.status!r} version={self.version!r}>"


class TestScenario(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One case in a plan -- "create an order", "reject a duplicate payment".

    ``scenario_key`` is the plan-stable key the run side echoes back.  It is
    unique per plan, which is what lets a run record name its source scenario
    without depending on a row that may since have been edited.
    """

    __tablename__ = "test_scenarios"
    __table_args__ = (UniqueConstraint("plan_id", "scenario_key"),)

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    scenario_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    description: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    expected: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    risk_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="medium", server_default=text("'medium'")
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    plan: Mapped[TestPlan] = relationship("TestPlan", back_populates="scenarios", lazy="joined")
    steps: Mapped[list[TestStep]] = relationship(
        "TestStep", back_populates="scenario", lazy="raise", passive_deletes=True
    )
    assertions: Mapped[list[TestAssertion]] = relationship(
        "TestAssertion", back_populates="scenario", lazy="raise", passive_deletes=True
    )
    run_scenarios: Mapped[list[RunScenario]] = relationship(
        "RunScenario", back_populates="source_scenario", lazy="raise", passive_deletes=True
    )


class TestStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One operation inside a scenario.

    ``description`` is the ``LocalizedText`` the frontend renders as the step
    (it has no separate ``name``); ``step_type`` distinguishes a request from an
    extraction or an assertion.  ``produces`` / ``consumes`` are variable names,
    not foreign keys -- there is no variable table to point at, and a run's
    variables live in its own context.

    ``config`` is the shape that varies by ``step_type`` and is required; its
    structure is not fixed by this schema.
    """

    __tablename__ = "test_steps"
    __table_args__ = (UniqueConstraint("scenario_id", "step_key"),)

    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_scenarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_key: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    step_type: Mapped[str] = mapped_column(String(50), nullable=False)
    endpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        # SET NULL: re-analysing a document replaces its endpoints, and losing an
        # endpoint must not delete the steps that named it.
        ForeignKey("api_endpoints.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    depends_on: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    produces: Mapped[str | None] = mapped_column(String(255), nullable=True)
    consumes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    scenario: Mapped[TestScenario] = relationship(
        "TestScenario", back_populates="steps", lazy="joined"
    )
    endpoint: Mapped[ApiEndpoint | None] = relationship(
        "ApiEndpoint", back_populates="test_steps", lazy="joined"
    )
    assertions: Mapped[list[TestAssertion]] = relationship(
        "TestAssertion", back_populates="step", lazy="raise", passive_deletes=True
    )
    run_steps: Mapped[list[RunStep]] = relationship(
        "RunStep", back_populates="source_step", lazy="raise", passive_deletes=True
    )


class TestAssertion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A check written against a scenario, and optionally against one step.

    ``step_id`` is nullable because a scenario-level assertion has no step to
    hang off -- that is why ``scenario_id`` is not redundant and cannot be
    dropped: it is the only anchor such an assertion has.

    ``assertion_key`` is unique across the whole scenario rather than per step.
    That means a generator must namespace its keys (``{step_key}.{name}``)
    rather than emit bare ``status_200`` twice; the alternative,
    ``UNIQUE(step_id, assertion_key)``, would enforce nothing at all for
    scenario-level assertions, since PostgreSQL treats NULLs as distinct.
    """

    __tablename__ = "test_assertions"
    __table_args__ = (UniqueConstraint("scenario_id", "assertion_key"),)

    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_scenarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        # CASCADE, not SET NULL: nulling this would silently demote a step-level
        # assertion into a scenario-level one and change what the test means.
        ForeignKey("test_steps.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    assertion_key: Mapped[str] = mapped_column(String(100), nullable=False)
    assertion_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    expression: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    description: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    scenario: Mapped[TestScenario] = relationship(
        "TestScenario", back_populates="assertions", lazy="joined"
    )
    step: Mapped[TestStep | None] = relationship(
        "TestStep", back_populates="assertions", lazy="joined"
    )
    run_assertions: Mapped[list[RunAssertion]] = relationship(
        "RunAssertion", back_populates="source_assertion", lazy="raise", passive_deletes=True
    )
