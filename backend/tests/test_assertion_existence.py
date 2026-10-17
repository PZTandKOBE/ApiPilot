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
