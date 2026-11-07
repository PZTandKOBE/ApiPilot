"""The approval fingerprint: which plan changes move the digest, and which do not.

The fingerprint is the receipt binding an approval to content. These tests
mutate one stored field at a time and recompute the digest through the same
loader approval and run creation use, so the coverage is the real one rather
than a copy of the canonicalizer.

Execution-critical fields must change the digest; display-only copy must not,
because renaming a plan is not a change to what it does.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

import pytest
from sqlalchemy import select, update

from backend.db.models.agent import TestAssertion, TestPlan, TestScenario, TestStep
from backend.db.models.project import ApiSpec, Project
from backend.services.spec_identity import spec_id_for
from backend.schemas.run import PlanPayload
from backend.services import plan_hash, runs

pytestmark = pytest.mark.anyio

PLAN_ID = "plan_c20_hash"


def _payload(*, project_id: str, spec_id: str) -> PlanPayload:
    return PlanPayload.model_validate(
        {
            "id": PLAN_ID,
            "projectId": project_id,
            "specId": spec_id,
            "name": {"text": "hash plan"},
            "goal": {"text": "prove the fingerprint covers execution"},
            "riskLevel": "low",
            "status": "draft",
            "source": "generated",
            "generatedAt": "2026-11-05T00:00:00Z",
            "scenarios": [
                {
                    "id": "scenario_c20",
                    "index": 0,
                    "name": {"text": "scenario"},
                    "description": {"text": "description"},
                    "expected": {"text": "expected"},
                    "riskLevel": "low",
                    "steps": [
                        {
                            "id": "step_c20_request",
                            "index": 0,
                            "kind": "request",
                            "description": {"text": "request"},
                            "endpointId": None,
                            "method": "GET",
                            "path": "/items/{{itemId}}",
                            "produces": None,
                            "consumes": ["itemId"],
                            "body": {"name": "example"},
                            "bodyPresent": True,
                        },
                        {
                            "id": "step_c20_extract",
                            "index": 1,
                            "kind": "extract",
                            "description": {"text": "extract"},
                            "endpointId": None,
                            "method": None,
                            "path": None,
                            "produces": "itemId",
                            "consumes": [],
                            "sourcePath": "$[0].id",
                            "sourceStepId": "step_c20_request",
                        },
                        {
                            "id": "step_c20_assert",
                            "index": 2,
                            "kind": "assert",
                            "description": {"text": "assert"},
                            "endpointId": None,
                            "method": None,
                            "path": None,
                            "produces": None,
                            "consumes": [],
                        },
                    ],
                    "assertions": [
                        {
                            "id": "assertion_c20",
                            "kind": "status",
                            "target": "status",
                            "expected": "200",
                            "description": {"text": "assertion"},
                            "stepId": "step_c20_assert",
                        }
                    ],
                }
            ],
        }
    )


class _Rows:
    plan: TestPlan
    scenario: TestScenario
    request_step: TestStep
    extract_step: TestStep
    assert_step: TestStep
    assertion: TestAssertion


async def _seed(fixtures, stack) -> _Rows:
    project_public_id = (
        await fixtures.session.execute(
            select(Project.public_id).where(Project.id == stack["project"])
        )
    ).scalar_one()
    slug = (
        await fixtures.session.execute(
            select(ApiSpec.slug).where(ApiSpec.id == stack["spec"])
        )
    ).scalar_one()

    payload = _payload(project_id=project_public_id, spec_id=spec_id_for(slug))
    materialization = await runs._create_plan_tree(
        fixtures.session,
        project_id=stack["project"],
        spec_id=stack["spec"],
        plan=payload,
    )

    scenario = (
        await fixtures.session.execute(
            select(TestScenario).where(TestScenario.plan_id == materialization.plan_id)
        )
    ).scalar_one()
    steps = {
        step.step_key: step
        for step in (
            await fixtures.session.execute(
                select(TestStep).where(TestStep.scenario_id == scenario.id)
            )
        ).scalars()
    }
    assertion = (
        await fixtures.session.execute(
            select(TestAssertion).where(TestAssertion.scenario_id == scenario.id)
        )
    ).scalar_one()
    plan = await fixtures.session.get(TestPlan, materialization.plan_id)

    rows = _Rows()
    rows.plan = plan
    rows.scenario = scenario
    rows.request_step = steps["step_c20_request"]
    rows.extract_step = steps["step_c20_extract"]
    rows.assert_step = steps["step_c20_assert"]
    rows.assertion = assertion
    return rows


async def _hash(fixtures, rows, project_public_id: str) -> str:
    stored = await plan_hash.load_stored_plan(
        fixtures.session, plan=rows.plan, project_public_id=project_public_id
    )
    return stored.content_hash


async def _config(session, step: TestStep) -> dict[str, Any]:
    config = step.config
    assert isinstance(config, dict)
    return dict(config)


async def _set_step_config(session, step: TestStep, **changes: Any) -> None:
    config = await _config(session, step)
    config.update(changes)
    await session.execute(
        update(TestStep).where(TestStep.id == step.id).values(config=config)
    )
    await session.flush()


async def _mutate_method(fixtures, rows) -> None:
    await _set_step_config(fixtures.session, rows.request_step, method="POST")


async def _mutate_path(fixtures, rows) -> None:
    await _set_step_config(fixtures.session, rows.request_step, path="/other")


async def _mutate_body(fixtures, rows) -> None:
    await _set_step_config(
        fixtures.session, rows.request_step, body={"name": "changed"}
    )


async def _mutate_body_presence(fixtures, rows) -> None:
    await _set_step_config(fixtures.session, rows.request_step, bodyPresent=False)


async def _mutate_produces(fixtures, rows) -> None:
    await fixtures.session.execute(
        update(TestStep)
        .where(TestStep.id == rows.extract_step.id)
        .values(produces="otherId")
    )
    await fixtures.session.flush()


async def _mutate_source_path(fixtures, rows) -> None:
    await _set_step_config(fixtures.session, rows.extract_step, sourcePath="$.id")


async def _mutate_source_step(fixtures, rows) -> None:
    await _set_step_config(
        fixtures.session, rows.extract_step, sourceStepId="step_c20_assert"
    )


async def _mutate_step_order(fixtures, rows) -> None:
    await fixtures.session.execute(
        update(TestStep)
        .where(TestStep.id == rows.request_step.id)
        .values(sort_order=5)
    )
    await fixtures.session.flush()


async def _mutate_step_key(fixtures, rows) -> None:
    await fixtures.session.execute(
        update(TestStep)
        .where(TestStep.id == rows.request_step.id)
        .values(step_key="step_c20_request_renamed")
    )
    await fixtures.session.flush()


async def _mutate_assertion_expected(fixtures, rows) -> None:
    await fixtures.session.execute(
        update(TestAssertion)
        .where(TestAssertion.id == rows.assertion.id)
        .values(expected_value="201")
    )
    await fixtures.session.flush()


async def _mutate_assertion_target(fixtures, rows) -> None:
    await fixtures.session.execute(
        update(TestAssertion)
        .where(TestAssertion.id == rows.assertion.id)
        .values(target="body.id")
    )
    await fixtures.session.flush()


async def _mutate_assertion_kind(fixtures, rows) -> None:
    await fixtures.session.execute(
        update(TestAssertion)
        .where(TestAssertion.id == rows.assertion.id)
        .values(assertion_type="header", target="header.x-request-id")
    )
    await fixtures.session.flush()


async def _mutate_assertion_binding(fixtures, rows) -> None:
    # Bind to a different step.  Clearing the binding entirely would resolve to
    # the same checkpoint step in the effective-binding digest, which is the
    # execution-equivalent case (covered by its own test below).
    await fixtures.session.execute(
        update(TestAssertion)
        .where(TestAssertion.id == rows.assertion.id)
        .values(step_id=rows.request_step.id)
    )
    await fixtures.session.flush()


async def _mutate_scenario_order(fixtures, rows) -> None:
    await fixtures.session.execute(
        update(TestScenario)
        .where(TestScenario.id == rows.scenario.id)
        .values(sort_order=3)
    )
    await fixtures.session.flush()


async def _mutate_scenario_key(fixtures, rows) -> None:
    await fixtures.session.execute(
        update(TestScenario)
        .where(TestScenario.id == rows.scenario.id)
        .values(scenario_key="scenario_c20_renamed")
    )
    await fixtures.session.flush()


EXECUTION_MUTATORS: list[tuple[str, Callable]] = [
    ("step method", _mutate_method),
    ("step path", _mutate_path),
    ("step body", _mutate_body),
    ("step body presence", _mutate_body_presence),
    ("step produces", _mutate_produces),
    ("extract source path", _mutate_source_path),
    ("extract source step", _mutate_source_step),
    ("step order", _mutate_step_order),
    ("step key", _mutate_step_key),
    ("assertion expected", _mutate_assertion_expected),
    ("assertion target", _mutate_assertion_target),
    ("assertion kind", _mutate_assertion_kind),
    ("assertion binding", _mutate_assertion_binding),
    ("scenario order", _mutate_scenario_order),
    ("scenario key", _mutate_scenario_key),
]


@pytest.mark.parametrize("label, mutate", EXECUTION_MUTATORS, ids=[item[0] for item in EXECUTION_MUTATORS])
async def test_execution_field_changes_move_the_digest(fixtures, stack, label, mutate) -> None:
    rows = await _seed(fixtures, stack)
    from backend.db.models.project import ApiSpec, Project

    project_public_id = (
        await fixtures.session.execute(
            select(Project.public_id).where(Project.id == stack["project"])
        )
    ).scalar_one()
    before = await _hash(fixtures, rows, project_public_id)

    await mutate(fixtures, rows)

    after = await _hash(fixtures, rows, project_public_id)
    assert after != before, f"changing {label} did not change the approval fingerprint"
    assert len(before) == 64


DISPLAY_MUTATORS: list[tuple[str, Callable]] = [
    ("plan name", lambda f, r: _set_plan_json(f, r, "name", {"text": "renamed"})),
    ("plan goal", lambda f, r: _set_plan_json(f, r, "description", {"text": "new goal"})),
    ("scenario name", lambda f, r: _set_scenario_json(f, r, "name", {"text": "renamed"})),
    ("scenario description", lambda f, r: _set_scenario_json(f, r, "description", {"text": "new"})),
    ("scenario expected", lambda f, r: _set_scenario_json(f, r, "expected", {"text": "new"})),
    ("step description", lambda f, r: _set_step_json(f, r, "description", {"text": "new"})),
    ("assertion description", lambda f, r: _set_assertion_json(f, r, "description", {"text": "new"})),
]


async def _set_plan_json(fixtures, rows, column: str, value: Any) -> None:
    from backend.db.models.agent import TestPlan as _Plan

    await fixtures.session.execute(
        update(_Plan).where(_Plan.id == rows.plan.id).values({column: value})
    )
    await fixtures.session.flush()


async def _set_scenario_json(fixtures, rows, column: str, value: Any) -> None:
    await fixtures.session.execute(
        update(TestScenario)
        .where(TestScenario.id == rows.scenario.id)
        .values({column: value})
    )
    await fixtures.session.flush()


async def _set_step_json(fixtures, rows, column: str, value: Any) -> None:
    await fixtures.session.execute(
        update(TestStep)
        .where(TestStep.id == rows.request_step.id)
        .values({column: value})
    )
    await fixtures.session.flush()


async def _set_assertion_json(fixtures, rows, column: str, value: Any) -> None:
    await fixtures.session.execute(
        update(TestAssertion)
        .where(TestAssertion.id == rows.assertion.id)
        .values({column: value})
    )
    await fixtures.session.flush()


@pytest.mark.parametrize("label, mutate", DISPLAY_MUTATORS, ids=[item[0] for item in DISPLAY_MUTATORS])
async def test_display_only_changes_keep_the_digest(fixtures, stack, label, mutate) -> None:
    rows = await _seed(fixtures, stack)
    from backend.db.models.project import Project

    project_public_id = (
        await fixtures.session.execute(
            select(Project.public_id).where(Project.id == stack["project"])
        )
    ).scalar_one()
    before = await _hash(fixtures, rows, project_public_id)

    await mutate(fixtures, rows)

    after = await _hash(fixtures, rows, project_public_id)
    assert after == before, f"changing display field {label} should not invalidate approval"


async def test_an_unbound_assertion_resolves_to_the_checkpoint_digest(
    fixtures, stack,
) -> None:
    """Null binding and explicit checkpoint binding are execution-equivalent."""
    rows = await _seed(fixtures, stack)
    project_public_id = (
        await fixtures.session.execute(
            select(Project.public_id).where(Project.id == stack["project"])
        )
    ).scalar_one()
    baseline = await _hash(fixtures, rows, project_public_id)

    await fixtures.session.execute(
        update(TestAssertion)
        .where(TestAssertion.id == rows.assertion.id)
        .values(step_id=None)
    )
    await fixtures.session.flush()
    unbound = await _hash(fixtures, rows, project_public_id)
    assert unbound == baseline, "an unbound assertion must hash as its checkpoint step"

    await fixtures.session.execute(
        update(TestAssertion)
        .where(TestAssertion.id == rows.assertion.id)
        .values(step_id=rows.request_step.id)
    )
    await fixtures.session.flush()
    rebound = await _hash(fixtures, rows, project_public_id)
    assert rebound != baseline, "binding the assertion to another step must change the digest"
