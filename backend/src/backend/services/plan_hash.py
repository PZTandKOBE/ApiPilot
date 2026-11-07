"""The approval fingerprint for a stored test plan.

An approval is only meaningful if it names the content it approved. This
module answers "what content does this plan row hold?" and turns it into a
stable SHA-256 digest (test_plans.content_hash).

Two callers, one function, so the two can never disagree:

* approving a plan stores the digest of its rows as they are now;
* creating a run recomputes the same digest and refuses to execute when it
  no longer matches the stored receipt.

What is covered: every plan-side field that can change what the executor
sends or judges.  Those fields are copied into the run snapshot at creation
(produces, body/body_present, method, path, sourcePath/sourceStepId through
config), so the fingerprint and the snapshot describe the same content; the
executor no longer reads the plan at all.  Stable keys, ordering and the
effective assertion binding are covered too: an assertion that names no step
hashes as the checkpoint step the run snapshot will bind it to.

load_run_content() rebuilds the same canonical document from the run tables;
create_run compares that digest with the approval receipt after writing the
snapshot, so a missing or altered execution field is detected even when the
source plan is unchanged.

What is deliberately excluded: display copy only. Plan name/description,
scenario/step/assertion descriptions, scenario expected text, and risk
levels do not change any HTTP request or assertion. Renaming a plan must not
trigger a re-review that teaches reviewers to click through.

Canonical form: JSON with sorted keys, arrays ordered exactly as the executor
reads them (scenario/step sort_order with the stable key as tiebreaker,
assertions by assertion_key), prefixed with a format version. The digest is
therefore reproducible and independent of PostgreSQL JSONB key order.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models.agent import TestAssertion, TestPlan, TestScenario, TestStep
from backend.db.models.project import ApiSpec
from backend.db.models.result import RunAssertion, RunScenario, RunStep
from backend.schemas.run import PlanPayload
from backend.services.spec_identity import spec_id_for

__all__ = [
    "PLAN_CONTENT_VERSION",
    "PlanContentError",
    "StoredPlan",
    "hash_content",
    "load_run_content",
    "load_stored_plan",
]

PLAN_CONTENT_VERSION = 1
"""Bump when the canonical shape changes; old receipts then stop matching."""

_HASH_DOMAIN = b"apipilot.plan-content.v1\n"

_METHOD_LIMIT = 20
_PATH_LIMIT = 1000


class PlanContentError(Exception):
    """The stored rows cannot be read as an executable plan.

    Services map this to a 409 refusal. A row set the executor could not run
    is a plan that must be reviewed again, not a 500.
    """


@dataclass(frozen=True)
class StoredPlan:
    """One plan row, its executable payload and the digest of its content."""

    plan_row_id: uuid.UUID
    public_id: str
    spec_row_id: uuid.UUID
    spec_id: str
    payload: PlanPayload
    content_hash: str


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _config_text(config: Any, key: str, limit: int) -> str | None:
    """One string out of JSONB, using the run snapshot acceptance rule.

    Mirrors runs._config_text: not a string, empty, or wider than the target
    column means absent. The same rule at approval and at execution keeps the
    digest and the snapshot reading the same value.
    """
    if not isinstance(config, Mapping):
        return None

    value = config.get(key)

    if isinstance(value, str) and 0 < len(value) <= limit:
        return value

    return None


def _config_flag(config: Any, key: str) -> bool:
    return isinstance(config, Mapping) and config.get(key) is True


def _config_body(config: Any) -> Any:
    if not isinstance(config, Mapping) or "body" not in config:
        return None
    return config["body"]


def _source_text(value: Any) -> str | None:
    """The Extract source fields, read exactly as the executor reads them."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _consumes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _localized(value: Any, *, fallback: Mapping[str, Any] | None = None) -> Any:
    """A JSONB LocalizedText, or the fallback when the column is empty."""
    if isinstance(value, Mapping) and ("key" in value or "text" in value):
        return dict(value)
    return dict(fallback) if fallback is not None else {"text": ""}


def _expected_text(value: Any) -> str:
    """Assertion expected as the wire contract carries it.

    Mirrors agent._plan_response: expected_value is JSONB, the contract field
    is str, and a non-string reads as empty rather than crashing a read.
    """
    return value if isinstance(value, str) else ""


def _canonical_content(scenarios: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The digest input: format version plus the executable plan tree."""
    return {"version": PLAN_CONTENT_VERSION, "scenarios": list(scenarios)}


def hash_content(content: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON document, hex encoded."""
    encoded = json.dumps(
        content,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(_HASH_DOMAIN + encoded).hexdigest()


async def _rows_for_plan(
    session: AsyncSession, plan_row_id: uuid.UUID
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    scenario_rows = (
        await session.execute(
            select(
                TestScenario.id,
                TestScenario.scenario_key,
                TestScenario.sort_order,
                TestScenario.risk_level,
                TestScenario.name,
                TestScenario.description,
                TestScenario.expected,
            )
            .where(TestScenario.plan_id == plan_row_id)
            .order_by(TestScenario.sort_order, TestScenario.scenario_key)
        )
    ).mappings().all()

    if not scenario_rows:
        return [], [], []

    scenario_ids = [row["id"] for row in scenario_rows]

    step_rows = (
        await session.execute(
            select(
                TestStep.scenario_id,
                TestStep.step_key,
                TestStep.sort_order,
                TestStep.step_type,
                TestStep.description,
                TestStep.config,
                TestStep.produces,
                TestStep.consumes,
            )
            .where(TestStep.scenario_id.in_(scenario_ids))
            .order_by(TestStep.scenario_id, TestStep.sort_order, TestStep.step_key)
        )
    ).mappings().all()

    assertion_rows = (
        await session.execute(
            select(
                TestAssertion.scenario_id,
                TestAssertion.assertion_key,
                TestAssertion.assertion_type,
                TestAssertion.target,
                TestAssertion.expected_value,
                TestAssertion.description,
                TestStep.step_key.label("bound_step_key"),
            )
            .join(TestScenario, TestScenario.id == TestAssertion.scenario_id)
            .outerjoin(TestStep, TestStep.id == TestAssertion.step_id)
            .where(TestScenario.plan_id == plan_row_id)
            .order_by(TestScenario.sort_order, TestAssertion.assertion_key)
        )
    ).mappings().all()

    return list(scenario_rows), list(step_rows), list(assertion_rows)


def _step_content(
    *,
    step_id: str,
    index: int,
    kind: str,
    method: str | None,
    path: str | None,
    body_present: bool,
    body: Any,
    produces: str | None,
    consumes: Sequence[str],
    source_path: str | None,
    source_step_id: str | None,
) -> dict[str, Any]:
    """The canonical step document, shared by plan and run snapshots."""
    return {
        "id": step_id,
        "index": index,
        "kind": kind,
        "method": method,
        "path": path,
        "body_present": body_present,
        "body": body,
        "produces": produces,
        "consumes": list(consumes),
        "source_path": source_path,
        "source_step_id": source_step_id,
    }


def _assertion_content(
    *,
    assertion_id: str,
    kind: str,
    target: str,
    expected: Any,
    step_id: str | None,
) -> dict[str, Any]:
    """The canonical assertion document, shared by plan and run snapshots."""
    return {
        "id": assertion_id,
        "kind": kind,
        "target": target,
        "expected": expected,
        "step_id": step_id,
    }


def _scenario_content(
    *,
    scenario_id: str,
    index: int,
    steps: Sequence[dict[str, Any]],
    assertions: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """The canonical scenario document, shared by plan and run snapshots."""
    return {
        "id": scenario_id,
        "index": index,
        "steps": list(steps),
        "assertions": list(assertions),
    }


def _checkpoint_step_key(step_rows: Sequence[Mapping[str, Any]]) -> str | None:
    """The step an unbound assertion hangs off, mirroring _insert_run_tree.

    The plan may name no step for an assertion; the run snapshot binds it to the
    first assert step, otherwise the scenario's last step.  The approval digest
    must include that effective binding, or a run created from an unbound
    assertion would have a different digest from its approved receipt.
    """
    for row in step_rows:
        if row["step_type"] == "assert":
            return row["step_key"]
    return step_rows[-1]["step_key"] if step_rows else None


def _build_content(
    scenario_rows: Sequence[Mapping[str, Any]],
    step_rows: Sequence[Mapping[str, Any]],
    assertion_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    steps_by_scenario: dict[uuid.UUID, list[Mapping[str, Any]]] = {}
    for row in step_rows:
        steps_by_scenario.setdefault(row["scenario_id"], []).append(row)

    assertions_by_scenario: dict[uuid.UUID, list[Mapping[str, Any]]] = {}
    for row in assertion_rows:
        assertions_by_scenario.setdefault(row["scenario_id"], []).append(row)

    scenarios: list[dict[str, Any]] = []
    for scenario in scenario_rows:
        steps = []
        for step in steps_by_scenario.get(scenario["id"], []):
            config = _as_mapping(step["config"])
            body_present = _config_flag(config, "bodyPresent")
            steps.append(
                _step_content(
                    step_id=step["step_key"],
                    index=step["sort_order"],
                    kind=step["step_type"],
                    method=_config_text(config, "method", _METHOD_LIMIT),
                    path=_config_text(config, "path", _PATH_LIMIT),
                    body_present=body_present,
                    body=_config_body(config) if body_present else None,
                    produces=step["produces"],
                    consumes=_consumes(step["consumes"]),
                    source_path=_source_text(config.get("sourcePath")),
                    source_step_id=_source_text(config.get("sourceStepId")),
                )
            )

        scenario_steps = steps_by_scenario.get(scenario["id"], [])
        step_keys = {row["step_key"] for row in scenario_steps}
        checkpoint = _checkpoint_step_key(scenario_steps)

        assertions = [
            _assertion_content(
                assertion_id=row["assertion_key"],
                kind=row["assertion_type"],
                target=row["target"],
                expected=row["expected_value"],
                step_id=(
                    row["bound_step_key"]
                    if row["bound_step_key"] in step_keys
                    else checkpoint
                ),
            )
            for row in assertions_by_scenario.get(scenario["id"], [])
        ]

        scenarios.append(
            _scenario_content(
                scenario_id=scenario["scenario_key"],
                index=scenario["sort_order"],
                steps=steps,
                assertions=assertions,
            )
        )

    return _canonical_content(scenarios)


def _payload_from_rows(
    *,
    plan: TestPlan,
    project_public_id: str,
    spec_id: str,
    scenario_rows: Sequence[Mapping[str, Any]],
    step_rows: Sequence[Mapping[str, Any]],
    assertion_rows: Sequence[Mapping[str, Any]],
) -> PlanPayload:
    steps_by_scenario: dict[uuid.UUID, list[Mapping[str, Any]]] = {}
    for row in step_rows:
        steps_by_scenario.setdefault(row["scenario_id"], []).append(row)

    assertions_by_scenario: dict[uuid.UUID, list[Mapping[str, Any]]] = {}
    for row in assertion_rows:
        assertions_by_scenario.setdefault(row["scenario_id"], []).append(row)

    scenarios = []
    for scenario in scenario_rows:
        steps = []
        for step in steps_by_scenario.get(scenario["id"], []):
            config = _as_mapping(step["config"])
            body_present = _config_flag(config, "bodyPresent")
            steps.append(
                {
                    "id": step["step_key"],
                    "index": step["sort_order"],
                    "kind": step["step_type"],
                    "description": _localized(step["description"], fallback={"text": ""}),
                    "endpointId": None,
                    "method": _config_text(config, "method", _METHOD_LIMIT),
                    "path": _config_text(config, "path", _PATH_LIMIT),
                    "produces": step["produces"],
                    "consumes": _consumes(step["consumes"]),
                    "sourcePath": _source_text(config.get("sourcePath")),
                    "sourceStepId": _source_text(config.get("sourceStepId")),
                    "body": _config_body(config) if body_present else None,
                    "bodyPresent": body_present,
                }
            )

        assertions = [
            {
                "id": row["assertion_key"],
                "kind": row["assertion_type"],
                "target": row["target"],
                "expected": _expected_text(row["expected_value"]),
                "description": _localized(row["description"], fallback={"text": ""}),
                "stepId": row["bound_step_key"],
            }
            for row in assertions_by_scenario.get(scenario["id"], [])
        ]

        scenarios.append(
            {
                "id": scenario["scenario_key"],
                "index": scenario["sort_order"],
                "name": _localized(scenario["name"], fallback={"text": ""}),
                "description": _localized(
                    scenario["description"], fallback={"text": ""}
                ),
                "riskLevel": scenario["risk_level"],
                "steps": steps,
                "expected": _localized(scenario["expected"], fallback={"text": ""}),
                "assertions": assertions,
            }
        )

    data = {
        "id": plan.public_id,
        "projectId": project_public_id,
        "specId": spec_id,
        "version": plan.version,
        "name": _localized(plan.name, fallback={"text": ""}),
        "goal": _localized(plan.description, fallback={"text": ""}),
        "riskLevel": plan.risk_level,
        "status": plan.status,
        "scenarios": scenarios,
        "source": plan.source,
        "generatedAt": plan.created_at,
        "approvedAt": plan.approved_at,
        "rejectedAt": plan.rejected_at,
        "rejectionReason": plan.rejection_reason,
    }

    try:
        return PlanPayload.model_validate(data)
    except ValidationError as exc:
        raise PlanContentError(
            "the stored plan is not a valid executable plan: " + str(exc)
        ) from exc


async def load_run_content(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    consumes_by_step: Mapping[tuple[str, str], Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Rebuild the canonical executable content from the Run rows themselves.

    This is the snapshot-side twin of _build_content: same shared builders,
    same ordering, same digest domain.  "consumes" is the one field absent from
    the run schema; the caller passes it from the approved payload because it
    is plan-validation metadata, not execution input.  Every field the executor
    reads comes from run_scenarios / run_steps / run_assertions.
    """
    scenario_rows = (
        await session.execute(
            select(
                RunScenario.id,
                RunScenario.scenario_key,
                RunScenario.sort_order,
            )
            .where(RunScenario.run_id == run_id)
            .order_by(RunScenario.sort_order, RunScenario.scenario_key)
        )
    ).mappings().all()

    if not scenario_rows:
        return _canonical_content([])

    scenario_ids = [row["id"] for row in scenario_rows]

    step_rows = (
        await session.execute(
            select(
                RunStep.id,
                RunStep.run_scenario_id,
                RunStep.step_key,
                RunStep.sort_order,
                RunStep.step_type,
                RunStep.method,
                RunStep.path,
                RunStep.source_path,
                RunStep.source_step_key,
                RunStep.produces,
                RunStep.body,
                RunStep.body_present,
            )
            .where(RunStep.run_scenario_id.in_(scenario_ids))
            .order_by(RunStep.run_scenario_id, RunStep.sort_order, RunStep.step_key)
        )
    ).mappings().all()

    assertion_rows = (
        await session.execute(
            select(
                RunAssertion.run_scenario_id,
                RunAssertion.assertion_key,
                RunAssertion.assertion_type,
                RunAssertion.target,
                RunAssertion.expected_value,
                RunStep.step_key.label("bound_step_key"),
            )
            .outerjoin(RunStep, RunStep.id == RunAssertion.run_step_id)
            .where(RunAssertion.run_scenario_id.in_(scenario_ids))
            .order_by(RunAssertion.run_scenario_id, RunAssertion.assertion_key)
        )
    ).mappings().all()

    consumes = consumes_by_step or {}
    steps_by_scenario: dict[uuid.UUID, list[Mapping[str, Any]]] = {}
    for row in step_rows:
        steps_by_scenario.setdefault(row["run_scenario_id"], []).append(row)

    assertions_by_scenario: dict[uuid.UUID, list[Mapping[str, Any]]] = {}
    for row in assertion_rows:
        assertions_by_scenario.setdefault(row["run_scenario_id"], []).append(row)

    scenarios: list[dict[str, Any]] = []
    for scenario in scenario_rows:
        steps = [
            _step_content(
                step_id=step["step_key"],
                index=step["sort_order"],
                kind=step["step_type"],
                method=step["method"],
                path=step["path"],
                body_present=step["body_present"],
                body=step["body"],
                produces=step["produces"],
                consumes=consumes.get(
                    (scenario["scenario_key"], step["step_key"]), ()
                ),
                source_path=step["source_path"],
                source_step_id=step["source_step_key"],
            )
            for step in steps_by_scenario.get(scenario["id"], [])
        ]

        assertions = [
            _assertion_content(
                assertion_id=row["assertion_key"],
                kind=row["assertion_type"],
                target=row["target"],
                expected=row["expected_value"],
                step_id=row["bound_step_key"],
            )
            for row in assertions_by_scenario.get(scenario["id"], [])
        ]

        scenarios.append(
            _scenario_content(
                scenario_id=scenario["scenario_key"],
                index=scenario["sort_order"],
                steps=steps,
                assertions=assertions,
            )
        )

    return _canonical_content(scenarios)


async def load_stored_plan(
    session: AsyncSession, *, plan: TestPlan, project_public_id: str
) -> StoredPlan:
    """Read one plan row and return its payload plus the digest of its content.

    Both are built from the same rows in the same call: a run cannot be built
    from content that was never fingerprinted.
    """
    slug = (
        await session.execute(select(ApiSpec.slug).where(ApiSpec.id == plan.spec_id))
    ).scalar_one_or_none()

    if slug is None:  # pragma: no cover - the FK is NO ACTION
        raise PlanContentError("the plan specification row is gone")

    scenario_rows, step_rows, assertion_rows = await _rows_for_plan(session, plan.id)

    content = _build_content(scenario_rows, step_rows, assertion_rows)
    payload = _payload_from_rows(
        plan=plan,
        project_public_id=project_public_id,
        spec_id=spec_id_for(slug),
        scenario_rows=scenario_rows,
        step_rows=step_rows,
        assertion_rows=assertion_rows,
    )

    return StoredPlan(
        plan_row_id=plan.id,
        public_id=plan.public_id,
        spec_row_id=plan.spec_id,
        spec_id=spec_id_for(slug),
        payload=payload,
        content_hash=hash_content(content),
    )
