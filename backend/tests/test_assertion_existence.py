"""Existence assertions mean existence, not equality with the word present.

A real run failed every "body.id is present" assertion while the field was
right there: the planner wrote expected="present" and the executor compared the
value to it.  These tests pin the meaning on both sides of that comparison.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.services import run_executor


def _response(body: Any) -> run_executor._Response:
    import json

    return run_executor._Response(
        status_code=200,
        headers={"content-type": "application/json"},
        text=json.dumps(body),
        json=body,
    )


def _assertion(kind: str, target: str, expected: str) -> run_executor._Assertion:
    return run_executor._Assertion(
        id=None, step_id=None, key="a", kind=kind, target=target, expected=expected
    )


@pytest.mark.parametrize("body,target", [
    ({"id": "order_123"}, "body.id"),
    ({"status": "created"}, "body.status"),
    ({"id": None}, "body.id"),
    ({"id": ""}, "body.id"),
    ({"id": 0}, "body.id"),
    ({"id": False}, "body.id"),
])
def test_a_field_that_exists_passes_a_present_assertion(body: Any, target: str) -> None:
    status, actual, _ = run_executor.evaluate_assertion(
        _assertion("field", target, "present"), _response(body)
    )

    assert status == run_executor.PASSED


def test_a_field_that_is_missing_fails_a_present_assertion() -> None:
    status, _, reason = run_executor.evaluate_assertion(
        _assertion("field", "body.id", "present"), _response({"status": "created"})
    )

    assert status == run_executor.FAILED
    assert reason == "the response body did not carry this field"


def test_a_missing_parent_object_is_not_a_present_field() -> None:
    status, _, _ = run_executor.evaluate_assertion(
        _assertion("field", "body.order.id", "present"), _response({"status": "created"})
    )

    assert status == run_executor.FAILED


def test_an_ordinary_value_assertion_still_compares_values() -> None:
    passed, actual, _ = run_executor.evaluate_assertion(
        _assertion("field", "body.status", "created"), _response({"status": "created"})
    )
    assert passed == run_executor.PASSED
    assert actual == "created"

    failed, _, _ = run_executor.evaluate_assertion(
        _assertion("field", "body.status", "created"), _response({"status": "shipped"})
    )
    assert failed == run_executor.FAILED


def test_a_value_that_happens_to_be_present_words_still_compares() -> None:
    """The sentinel must not hijack a value assertion whose expected is other text."""
    passed, _, _ = run_executor.evaluate_assertion(
        _assertion("field", "body.note", "present"), _response({"note": "present"})
    )
    assert passed == run_executor.PASSED


def test_a_status_assertion_is_untouched() -> None:
    passed, actual, _ = run_executor.evaluate_assertion(
        _assertion("status", "status", "200"), _response({"id": "x"})
    )
    assert passed == run_executor.PASSED
    assert actual == "200"


@pytest.mark.parametrize(
    "body,target,expected",
    [
        ([{"id": 101}], "body.$[0].id", "present"),
        ([{"title": "Example"}], "body.$[0].title", "present"),
        ([{"postId": 1}], "body.$[0].postId", "present"),
        ({"data": {"id": 101}}, "body.$.data.id", "present"),
        ({"data": [{"id": 101}]}, "body.$.data[0].id", "present"),
        ({"data": [{"id": 101}]}, "body.data[0].id", "present"),
        ([{"id": 0}], "body.$[0].id", "present"),
        ([{"active": False}], "body.$[0].active", "present"),
        ([{"id": None}], "body.$[0].id", "present"),
        ([{"id": ""}], "body.$[0].id", "present"),
    ],
)
def test_json_path_field_assertions_pass(body: Any, target: str, expected: str) -> None:
    status, actual, reason = run_executor.evaluate_assertion(
        _assertion("field", target, expected), _response(body)
    )

    assert status == run_executor.PASSED, reason
    assert actual is not None


@pytest.mark.parametrize(
    "body,target",
    [
        ([], "body.$[0].id"),
        ([{}], "body.$[0].id"),
        ({"data": {}}, "body.$.data.id"),
    ],
)
def test_json_path_missing_paths_fail(body: Any, target: str) -> None:
    status, actual, reason = run_executor.evaluate_assertion(
        _assertion("field", target, "present"), _response(body)
    )

    assert status == run_executor.FAILED
    assert actual is None
    assert reason is not None
    assert "did not resolve" in reason


def test_json_path_unknown_field_is_not_a_recursive_name_search() -> None:
    status, actual, reason = run_executor.evaluate_assertion(
        _assertion("field", "body.$[0].id", "present"),
        _response([{"nested": {"id": 101}}]),
    )

    assert status == run_executor.FAILED
    assert actual is None
    assert reason is not None
    assert "$[0].id" in reason


def test_json_path_invalid_syntax_fails_closed() -> None:
    status, actual, reason = run_executor.evaluate_assertion(
        _assertion("field", "body.$[0", "present"), _response([{"id": 101}])
    )

    assert status == run_executor.FAILED
    assert actual is None
    assert reason is not None
    assert "did not resolve" in reason


def test_json_path_against_non_json_fails_without_name_fallback() -> None:
    response = run_executor._Response(
        status_code=200,
        headers={"content-type": "text/plain"},
        text="not json",
        json=None,
    )
    status, actual, reason = run_executor.evaluate_assertion(
        _assertion("field", "body.$[0].id", "present"), response
    )

    assert status == run_executor.FAILED
    assert actual is None
    assert reason == "the response body is not JSON"


def test_plain_field_targets_still_use_the_legacy_dotted_walk() -> None:
    status, actual, _ = run_executor.evaluate_assertion(
        _assertion("field", "body.id", "present"), _response({"id": 101})
    )

    assert status == run_executor.PASSED
    assert actual == "101"
