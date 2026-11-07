"""Structural rules an executable plan must satisfy.

This module is deliberately independent of agent_plan.validate_plan.  That
validator is the generator's contract: it requires a draft status, a stable
expected plan id and the forbidden-value scan.  Approval and run creation have
none of those inputs -- they read a stored plan that may already be approved --
so they need a pure payload check with no request/generation metadata.

The input is always the normalized StoredPlan.payload.  Both
agent.approve_plan and runs._require_approved_plan call this module, so a plan
cannot be approved under one rule and materialized under another.

No session, no I/O, no mutation: it only reads the payload and returns issues.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.schemas.run import PlanPayload, PlanScenario, PlanStep
from backend.services.json_path import PathSyntaxError, parse_path

__all__ = [
    "PlanStructureError",
    "PlanStructureIssue",
    "collect_issues",
    "validate_executable_plan",
]


@dataclass(frozen=True)
class PlanStructureIssue:
    """One reason a plan cannot be executed, with enough context to debug it."""

    rule: str
    detail: str
    scenario_id: str | None = None
    step_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"rule": self.rule, "detail": self.detail}
        if self.scenario_id is not None:
            data["scenarioId"] = self.scenario_id
        if self.step_id is not None:
            data["stepId"] = self.step_id
        return data


class PlanStructureError(Exception):
    """The stored plan has no executable tree."""

    def __init__(self, issues: list[PlanStructureIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__(
            "the plan is not executable: "
            + "; ".join(issue.rule for issue in issues)
        )

    def as_dicts(self) -> list[dict[str, Any]]:
        return [issue.as_dict() for issue in self.issues]


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _source_fields(step: PlanStep) -> tuple[str, str]:
    """The extract source fields after the same blank-normalization the DB uses."""
    return (
        (step.source_path or "").strip(),
        (step.source_step_id or "").strip(),
    )


def _non_executable_sources(
    step: PlanStep,
    *,
    scenario_id: str,
    add: Any,
) -> None:
    """request / assert never own extract source fields."""
    if step.source_path is not None:
        add(
            "source-not-applicable",
            "a " + step.kind + " step carries source_path",
            scenario_id,
            step.id,
        )
    if step.source_step_id is not None:
        add(
            "source-not-applicable",
            "a " + step.kind + " step carries source_step_id",
            scenario_id,
            step.id,
        )


def _validate_extract(
    step: PlanStep,
    *,
    scenario_id: str,
    prior_requests: dict[str, PlanStep],
    add: Any,
) -> None:
    if _blank(step.produces):
        add(
            "extract-variable",
            "an extract step must name the variable it produces",
            scenario_id,
            step.id,
        )

    source_path, source_step_id = _source_fields(step)

    if not prior_requests:
        add(
            "extract-without-request",
            "an extract step needs a previous request in the same scenario",
            scenario_id,
            step.id,
        )

    if source_step_id and not source_path:
        add(
            "extract-source",
            "source_step_id is set but source_path is empty",
            scenario_id,
            step.id,
        )

    if source_path:
        try:
            parse_path(source_path)
        except PathSyntaxError as exc:
            add(
                "extract-source-path",
                "source_path is not a valid JSONPath: " + str(exc),
                scenario_id,
                step.id,
            )

    if source_step_id:
        target = prior_requests.get(source_step_id)
        if target is None:
            add(
                "extract-source",
                "source_step_id " + repr(source_step_id)
                + " is not an earlier request step in this scenario",
                scenario_id,
                step.id,
            )
        elif target.kind != "request":
            add(
                "extract-source-kind",
                "source_step_id " + repr(source_step_id) + " is not a request step",
                scenario_id,
                step.id,
            )


def _validate_step(
    step: PlanStep,
    *,
    scenario_id: str,
    prior_requests: dict[str, PlanStep],
    add: Any,
) -> None:
    if _blank(step.id):
        add("step-keys", "a step has an empty id", scenario_id, step.id)
        return

    if step.kind == "request":
        if _blank(step.method) or _blank(step.path):
            add(
                "request-target",
                "a request step must name both method and path",
                scenario_id,
                step.id,
            )
        _non_executable_sources(step, scenario_id=scenario_id, add=add)
        return

    if step.kind == "extract":
        _validate_extract(
            step,
            scenario_id=scenario_id,
            prior_requests=prior_requests,
            add=add,
        )
        return

    if step.kind == "assert":
        if step.method is not None or step.path is not None:
            add(
                "assert-target",
                "an assert step must not name a request",
                scenario_id,
                step.id,
            )
        _non_executable_sources(step, scenario_id=scenario_id, add=add)
        return

    add(
        "step-kind",
        "unknown step kind " + repr(step.kind),
        scenario_id,
        step.id,
    )


def _validate_assertions(scenario: PlanScenario, *, add: Any) -> None:
    step_by_key = {step.id: step for step in scenario.steps}

    for assertion in scenario.assertions:
        if _blank(assertion.id):
            add(
                "assertion-keys",
                "an assertion has an empty id",
                scenario.id,
                None,
            )

        if assertion.step_id is None or not assertion.step_id.strip():
            # Legacy plans may leave the binding null; the Run snapshot applies
            # its checkpoint fallback, and plan_hash hashes that effective binding.
            continue

        target = step_by_key.get(assertion.step_id.strip())
        if target is None:
            add(
                "assertion-binding",
                "assertion " + repr(assertion.id)
                + " names a step that does not exist in this scenario",
                scenario.id,
                assertion.step_id,
            )
        elif target.kind != "assert":
            add(
                "assertion-binding",
                "assertion " + repr(assertion.id)
                + " must bind to an assert step",
                scenario.id,
                assertion.step_id,
            )


def collect_issues(plan: PlanPayload) -> list[PlanStructureIssue]:
    """Every structural problem in one pass; never raises for content alone."""
    issues: list[PlanStructureIssue] = []

    def add(
        rule: str,
        detail: str,
        scenario_id: str | None = None,
        step_id: str | None = None,
    ) -> None:
        issues.append(
            PlanStructureIssue(
                rule=rule,
                detail=detail,
                scenario_id=scenario_id,
                step_id=step_id,
            )
        )

    if not plan.scenarios:
        add("no-scenarios", "a plan must contain at least one scenario")
        return issues

    scenario_keys: set[str] = set()
    scenario_indexes: set[int] = set()

    for scenario in plan.scenarios:
        if _blank(scenario.id):
            add("scenario-keys", "a scenario has an empty id")
        elif scenario.id in scenario_keys:
            add("scenario-keys", "scenario id " + repr(scenario.id) + " is duplicated")
        scenario_keys.add(scenario.id)

        if scenario.index in scenario_indexes:
            add(
                "scenario-order",
                "scenario index " + repr(scenario.index) + " is duplicated",
                scenario.id,
            )
        scenario_indexes.add(scenario.index)

        if not scenario.steps:
            add("no-steps", "a scenario must contain at least one step", scenario.id)
            _validate_assertions(scenario, add=add)
            continue

        step_keys: set[str] = set()
        step_indexes: set[int] = set()
        prior_requests: dict[str, PlanStep] = {}
        has_request = False

        # Execution order is the stored sort order after materialization; the
        # payload is already sorted by the loader, but sorting again makes the
        # "earlier request" rule depend on the index, not on list accident.
        for step in sorted(scenario.steps, key=lambda item: item.index):
            if _blank(step.id):
                add("step-keys", "a step has an empty id", scenario.id, step.id)
            elif step.id in step_keys:
                add(
                    "step-keys",
                    "step id " + repr(step.id) + " is duplicated",
                    scenario.id,
                    step.id,
                )
            step_keys.add(step.id)

            if step.index in step_indexes:
                add(
                    "step-order",
                    "step index " + repr(step.index) + " is duplicated",
                    scenario.id,
                    step.id,
                )
            step_indexes.add(step.index)

            _validate_step(
                step,
                scenario_id=scenario.id,
                prior_requests=prior_requests,
                add=add,
            )

            if step.kind == "request":
                has_request = True
                prior_requests[step.id] = step

        if not has_request:
            add(
                "scenario-without-request",
                "a scenario must contain at least one request step",
                scenario.id,
            )

        _validate_assertions(scenario, add=add)

    return issues


def validate_executable_plan(plan: PlanPayload) -> None:
    """Raise PlanStructureError when the payload cannot be executed."""
    issues = collect_issues(plan)
    if issues:
        raise PlanStructureError(issues)
