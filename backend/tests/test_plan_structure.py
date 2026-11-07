"""Pure structural rules for an executable plan.

These are the rules approval and run creation share.  The tests build the
normalized PlanPayload directly; no database is involved, which keeps the
failure mode of each rule visible.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from backend.schemas.run import PlanPayload
from backend.services.plan_structure import (
    PlanStructureError,
    collect_issues,
    validate_executable_plan,
)

PROJECT_ID = "prj_plan_structure"
SPEC_ID = "spec_plan_structure"


def _plan() -> dict[str, Any]:
    return {
        "id": "plan_plan_structure",
        "projectId": PROJECT_ID,
        "specId": SPEC_ID,
        "name": {"text": "structure plan"},
        "goal": {"text": "prove executable structure"},
        "riskLevel": "low",
        "status": "draft",
        "source": "generated",
        "generatedAt": "2026-11-07T00:00:00Z",
        "scenarios": [
            {
                "id": "scenario_primary",
                "index": 0,
                "name": {"text": "primary"},
                "description": {"text": "description"},
                "expected": {"text": "expected"},
                "riskLevel": "low",
                "steps": [
                    {
                        "id": "step_request",
                        "index": 0,
                        "kind": "request",
                        "description": {"text": "request"},
                        "endpointId": None,
                        "method": "GET",
                        "path": "/items",
                        "produces": None,
                        "consumes": [],
                    },
                    {
                        "id": "step_extract",
                        "index": 1,
                        "kind": "extract",
                        "description": {"text": "extract"},
                        "endpointId": None,
                        "method": None,
                        "path": None,
                        "produces": "itemId",
                        "consumes": [],
                        "sourcePath": "$.item.id",
                        "sourceStepId": "step_request",
                    },
                    {
                        "id": "step_assert",
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
                        "id": "assertion_status",
                        "kind": "status",
                        "target": "status",
                        "expected": "200",
                        "description": {"text": "assertion"},
                        "stepId": "step_assert",
                    }
                ],
            }
        ],
    }


def _payload() -> PlanPayload:
    return PlanPayload.model_validate(_plan())


def _rules(plan: PlanPayload) -> list[str]:
    return [issue.rule for issue in collect_issues(plan)]


def _step(plan: PlanPayload, scenario_index: int, step_index: int) -> Any:
    return plan.scenarios[scenario_index].steps[step_index]


def test_a_legal_plan_is_executable() -> None:
    validate_executable_plan(_payload())


def test_a_plan_without_scenarios_is_rejected() -> None:
    data = _plan()
    data["scenarios"] = []
    assert "no-scenarios" in _rules(PlanPayload.model_validate(data))


def test_a_scenario_without_steps_is_rejected() -> None:
    data = _plan()
    data["scenarios"][0]["steps"] = []
    assert "no-steps" in _rules(PlanPayload.model_validate(data))


def test_a_scenario_without_a_request_is_rejected() -> None:
    data = _plan()
    data["scenarios"][0]["steps"] = [
        {
            "id": "step_assert_only",
            "index": 0,
            "kind": "assert",
            "description": {"text": "assert"},
            "endpointId": None,
            "method": None,
            "path": None,
            "produces": None,
            "consumes": [],
        }
    ]
    data["scenarios"][0]["assertions"] = []
    assert "scenario-without-request" in _rules(PlanPayload.model_validate(data))


def test_a_request_does_not_need_a_source() -> None:
    plan = _payload()
    validate_executable_plan(plan)


def test_a_request_must_have_method_and_path() -> None:
    plan = _payload()
    _step(plan, 0, 0).path = None
    assert "request-target" in _rules(plan)


def test_an_extract_must_name_its_produced_variable() -> None:
    plan = _payload()
    _step(plan, 0, 1).produces = " "
    assert "extract-variable" in _rules(plan)


def test_legacy_extract_with_no_source_is_allowed() -> None:
    plan = _payload()
    extract = _step(plan, 0, 1)
    extract.source_path = None
    extract.source_step_id = None
    validate_executable_plan(plan)


def test_legacy_extract_with_path_only_is_allowed() -> None:
    plan = _payload()
    extract = _step(plan, 0, 1)
    extract.source_step_id = None
    validate_executable_plan(plan)


def test_source_step_without_path_is_rejected() -> None:
    plan = _payload()
    _step(plan, 0, 1).source_path = "   "
    assert "extract-source" in _rules(plan)


def test_source_path_must_parse() -> None:
    plan = _payload()
    _step(plan, 0, 1).source_path = "$..broken["
    assert "extract-source-path" in _rules(plan)


def test_source_step_must_exist() -> None:
    plan = _payload()
    _step(plan, 0, 1).source_step_id = "step_missing"
    assert "extract-source" in _rules(plan)


def test_source_step_must_be_earlier() -> None:
    plan = _payload()
    request = _step(plan, 0, 0)
    request.index = 2
    extract = _step(plan, 0, 1)
    extract.index = 1
    _step(plan, 0, 2).index = 3
    extract.source_step_id = request.id
    assert "extract-source" in _rules(plan)


def test_source_step_must_not_be_in_another_scenario() -> None:
    data = _plan()
    data["scenarios"].append(
        {
            "id": "scenario_other",
            "index": 1,
            "name": {"text": "other"},
            "description": {"text": "other"},
            "expected": {"text": "other"},
            "riskLevel": "low",
            "steps": [
                {
                    "id": "step_other_request",
                    "index": 0,
                    "kind": "request",
                    "description": {"text": "request"},
                    "endpointId": None,
                    "method": "GET",
                    "path": "/other",
                    "produces": None,
                    "consumes": [],
                }
            ],
            "assertions": [],
        }
    )
    plan = PlanPayload.model_validate(data)
    _step(plan, 0, 1).source_step_id = "step_other_request"
    assert "extract-source" in _rules(plan)


def test_source_step_must_be_a_request() -> None:
    plan = _payload()
    _step(plan, 0, 1).source_step_id = "step_assert"
    assert "extract-source" in _rules(plan)


def test_non_extract_steps_must_not_carry_source() -> None:
    plan = _payload()
    _step(plan, 0, 0).source_path = "$.id"
    _step(plan, 0, 2).source_step_id = "step_request"
    assert _rules(plan).count("source-not-applicable") == 2


def test_assert_cannot_have_method_or_path() -> None:
    plan = _payload()
    _step(plan, 0, 2).method = "GET"
    assert "assert-target" in _rules(plan)


def test_assertion_without_binding_is_allowed_for_checkpoint_fallback() -> None:
    plan = _payload()
    plan.scenarios[0].assertions[0].step_id = None
    validate_executable_plan(plan)


def test_assertion_binding_must_exist() -> None:
    plan = _payload()
    plan.scenarios[0].assertions[0].step_id = "step_missing"
    assert "assertion-binding" in _rules(plan)


def test_assertion_binding_must_target_an_assert_step() -> None:
    plan = _payload()
    plan.scenarios[0].assertions[0].step_id = "step_request"
    assert "assertion-binding" in _rules(plan)


def test_duplicate_scenario_and_step_keys_are_rejected() -> None:
    data = _plan()
    data["scenarios"].append(copy.deepcopy(data["scenarios"][0]))
    plan = PlanPayload.model_validate(data)
    rules = _rules(plan)
    assert "scenario-keys" in rules
    assert "scenario-order" in rules


def test_duplicate_step_keys_and_indexes_are_rejected() -> None:
    plan = _payload()
    _step(plan, 0, 0).id = "step_extract"
    _step(plan, 0, 1).index = 0
    rules = _rules(plan)
    assert "step-keys" in rules
    assert "step-order" in rules


def test_non_contiguous_order_is_allowed() -> None:
    plan = _payload()
    for step in plan.scenarios[0].steps:
        step.index *= 3
    plan.scenarios[0].index = 7
    validate_executable_plan(plan)


def test_error_carries_structured_issues() -> None:
    plan = _payload()
    plan.scenarios[0].steps[0].method = None
    with pytest.raises(PlanStructureError) as caught:
        validate_executable_plan(plan)
    issue = caught.value.as_dicts()[0]
    assert issue["rule"] == "request-target"
    assert issue["scenarioId"] == "scenario_primary"
    assert issue["stepId"] == "step_request"
