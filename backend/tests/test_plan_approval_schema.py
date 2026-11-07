"""The approval receipt exists in the database, not only in the model.

A model change that never reached a migration is the failure this catches: the
service would run against a database without the columns or checks it writes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.anyio

APPROVAL_COLUMNS = {
    "approved_by_guest_session_id",
    "approved_by_user_id",
    "content_hash",
}

APPROVAL_CHECKS = {
    "ck_test_plans_approval_actor_exclusive",
    "ck_test_plans_approval_actor_required",
    "ck_test_plans_approval_hash_required",
    "ck_test_plans_approval_hash_length",
    "ck_test_plans_rejection_clears_approval",
}

APPROVAL_FOREIGN_KEYS = {
    "fk_test_plans_approved_by_guest_session_id_guest_sessions",
    "fk_test_plans_approved_by_user_id_users",
}


async def test_test_plans_carries_the_approval_columns(read_session) -> None:
    rows = (
        await read_session.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_schema = 'public' and table_name = 'test_plans'"
            )
        )
    ).scalars().all()

    assert APPROVAL_COLUMNS <= set(rows)


async def test_the_approval_checks_are_enforced_by_postgres(read_session) -> None:
    rows = (
        await read_session.execute(
            text(
                "select conname from pg_constraint "
                "where conrelid = 'public.test_plans'::regclass and contype = 'c'"
            )
        )
    ).scalars().all()

    assert APPROVAL_CHECKS <= set(rows)


async def test_the_actor_foreign_keys_do_not_null_a_receipt(read_session) -> None:
    """NO ACTION, not SET NULL: deleting an actor with live plans is refused.

    A SET NULL here would null the actor of an approved row and violate the
    actor check inside the same statement; NO ACTION checks at statement end,
    after a project cascade has removed the plan rows.
    """
    rows = (
        await read_session.execute(
            text(
                "select conname, confdeltype from pg_constraint "
                "where conrelid = 'public.test_plans'::regclass and contype = 'f' "
                "and conname = any(:names)"
            ),
            {"names": list(APPROVAL_FOREIGN_KEYS)},
        )
    ).all()

    # asyncpg returns "char" columns as bytes; decode before comparing.
    found = {
        name: action.decode() if isinstance(action, bytes) else action
        for name, action in rows
    }
    assert set(found) == APPROVAL_FOREIGN_KEYS, found
    assert all(action == "a" for action in found.values()), found
