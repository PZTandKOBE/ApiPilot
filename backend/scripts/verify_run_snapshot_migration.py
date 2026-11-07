"""Scratch-database proof for the conservative run-snapshot migration.

Policy: every TestRun that exists before revision c7d8e9f0a1b2 is marked
snapshot_version=0.  The migration does not read test_steps at all, so it
cannot silently copy today's plan into a historical run.  This script builds
the cases that used to tempt a backfill (complete-looking, modified, missing
source, empty tree) and checks that all of them stay v0 with no copied fields.

    python scripts/verify_run_snapshot_migration.py

Exit code is the number of failed checks.  The scratch database is created and
dropped here; no application database is touched.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRATCH_DB = "aiata_run_snapshot_migration_test"
PREVIOUS_REVISION = "b1f2c3d4e5a6"

try:
    import backend  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    sys.path.insert(0, str(BACKEND_DIR / "src"))

from backend.db import database  # noqa: E402

import asyncpg  # noqa: E402


@dataclass
class Report:
    passed: int = 0
    failures: list[str] = field(default_factory=list)

    def check(self, label: str, condition: bool, detail: Any = None) -> None:
        if condition:
            self.passed += 1
            print("  PASS  " + label)
        else:
            self.failures.append(label)
            print("  FAIL  " + label + (("\n          " + str(detail)) if detail is not None else ""))

    def equal(self, label: str, actual: Any, expected: Any) -> None:
        self.check(label, actual == expected, "expected " + repr(expected) + ", got " + repr(actual))


def postgres_settings() -> dict[str, Any]:
    return {
        "host": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "user": os.getenv("POSTGRES_USER"),
        "password": os.getenv("POSTGRES_PASSWORD"),
    }


async def connect(database_name: str) -> asyncpg.Connection:
    return await asyncpg.connect(**postgres_settings(), database=database_name)


def alembic(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "POSTGRES_DB": SCRATCH_DB}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
    )


async def reset_scratch() -> None:
    connection = await connect("postgres")
    try:
        await connection.execute('DROP DATABASE IF EXISTS "' + SCRATCH_DB + '" WITH (FORCE)')
        await connection.execute('CREATE DATABASE "' + SCRATCH_DB + '"')
    finally:
        await connection.close()


async def drop_scratch() -> None:
    try:
        connection = await connect("postgres")
    except Exception:
        return
    try:
        await connection.execute('DROP DATABASE IF EXISTS "' + SCRATCH_DB + '" WITH (FORCE)')
    finally:
        await connection.close()


@dataclass
class Fixture:
    guest: uuid.UUID
    project: uuid.UUID
    spec: uuid.UUID
    plan: uuid.UUID
    scenario: uuid.UUID
    assertion: uuid.UUID
    steps: dict[str, uuid.UUID]


async def insert_fixture(connection: asyncpg.Connection) -> Fixture:
    guest = uuid.uuid4()
    project = uuid.uuid4()
    spec = uuid.uuid4()
    plan = uuid.uuid4()
    scenario = uuid.uuid4()
    assertion = uuid.uuid4()

    await connection.execute(
        "INSERT INTO guest_sessions (id, token_hash, expires_at, last_seen_at) "
        "VALUES ($1, $2, now() + interval '1 day', now())",
        guest,
        uuid.uuid4().hex + uuid.uuid4().hex,
    )
    await connection.execute(
        "INSERT INTO projects (id, public_id, name, guest_session_id) "
        "VALUES ($1, $2, $3, $4)",
        project,
        "prj_snapshot_" + uuid.uuid4().hex[:8],
        "Snapshot migration project",
        guest,
    )
    await connection.execute(
        "INSERT INTO api_specs (id, project_id, name, slug, spec_type, content_format, content) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        spec,
        project,
        "Snapshot migration spec",
        "snapshot_spec_" + uuid.uuid4().hex[:8],
        "openapi-3",
        "json",
        '{"openapi":"3.0.0","info":{"title":"x"},"paths":{}}',
    )
    await connection.execute(
        "INSERT INTO test_plans (id, project_id, spec_id, public_id, name) "
        "VALUES ($1, $2, $3, $4, $5::jsonb)",
        plan,
        project,
        spec,
        "plan_snapshot_" + uuid.uuid4().hex[:8],
        '{"text":"snapshot plan"}',
    )
    await connection.execute(
        "INSERT INTO test_scenarios (id, plan_id, scenario_key, name) "
        "VALUES ($1, $2, $3, $4::jsonb)",
        scenario,
        plan,
        "scenario_snapshot",
        '{"text":"scenario"}',
    )

    steps: dict[str, uuid.UUID] = {}
    definitions = {
        "request": {"method": "GET", "path": "/items"},
        "json_null": {"method": "POST", "path": "/null", "bodyPresent": True, "body": None},
        "empty_object": {"method": "POST", "path": "/object", "bodyPresent": True, "body": {}},
        "empty_array": {"method": "POST", "path": "/array", "bodyPresent": True, "body": []},
        "extract": {"sourcePath": "$.id", "sourceStepId": "request"},
    }
    for index, (key, config) in enumerate(definitions.items()):
        step_id = uuid.uuid4()
        steps[key] = step_id
        await connection.execute(
            "INSERT INTO test_steps "
            "(id, scenario_id, step_key, description, step_type, config, produces, consumes, "
            " sort_order, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4::jsonb, $5, $6::jsonb, $7, $8::jsonb, $9, "
            "        now() - interval '2 hours', now() - interval '2 hours')",
            step_id,
            scenario,
            key,
            '{"text":"' + key + '"}',
            "extract" if key == "extract" else "request",
            json.dumps(config),
            "produced_id" if key == "extract" else None,
            "[]",
            index,
        )

    await connection.execute(
        "INSERT INTO test_assertions "
        "(id, scenario_id, step_id, assertion_key, assertion_type, target, expected_value, description) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb)",
        assertion,
        scenario,
        steps["request"],
        "assertion_snapshot",
        "status",
        "status",
        '"200"',
        '{"text":"check"}',
    )

    return Fixture(guest, project, spec, plan, scenario, assertion, steps)


async def insert_run(
    connection: asyncpg.Connection,
    fixture: Fixture,
    *,
    name: str,
    step_keys: list[str],
    source_step_override: uuid.UUID | None | str = "keep",
    source_scenario: uuid.UUID | None = None,
) -> uuid.UUID:
    run_id = uuid.uuid4()
    await connection.execute(
        "INSERT INTO test_runs "
        "(id, project_id, plan_id, spec_id, plan_name, base_url, status, created_at) "
        "VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, now())",
        run_id,
        fixture.project,
        fixture.plan,
        fixture.spec,
        '{"text":"' + name + '"}',
        "http://127.0.0.1:9",
        "passed",
    )
    run_scenario = uuid.uuid4()
    await connection.execute(
        "INSERT INTO run_scenarios "
        "(id, run_id, source_scenario_id, scenario_key, name, risk_level, sort_order, status) "
        "VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)",
        run_scenario,
        run_id,
        fixture.scenario if source_scenario is None else source_scenario,
        "scenario_snapshot",
        '{"text":"scenario"}',
        "low",
        0,
        "pending",
    )
    for index, key in enumerate(step_keys):
        source = fixture.steps[key]
        if source_step_override == "keep":
            source_step_id = source
        elif source_step_override is None:
            source_step_id = None
        else:
            source_step_id = source_step_override
        await connection.execute(
            "INSERT INTO run_steps "
            "(id, run_scenario_id, source_step_id, step_key, description, step_type, "
            " method, path, sort_order, status) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10)",
            uuid.uuid4(),
            run_scenario,
            source_step_id,
            key,
            '{"text":"' + key + '"}',
            "extract" if key == "extract" else "request",
            None if key == "extract" else "GET",
            None if key == "extract" else "/items",
            index,
            "pending",
        )
    await connection.execute(
        "INSERT INTO run_assertions "
        "(id, run_scenario_id, source_assertion_id, assertion_key, assertion_type, "
        " target, expected_value, status) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)",
        uuid.uuid4(),
        run_scenario,
        fixture.assertion,
        "assertion_snapshot",
        "status",
        "status",
        '"200"',
        "skipped",
    )
    return run_id


async def insert_run_without_scenarios(connection: asyncpg.Connection, fixture: Fixture) -> uuid.UUID:
    run_id = uuid.uuid4()
    await connection.execute(
        "INSERT INTO test_runs "
        "(id, project_id, plan_id, spec_id, plan_name, base_url, status, created_at) "
        "VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, now())",
        run_id,
        fixture.project,
        fixture.plan,
        fixture.spec,
        '{"text":"empty run"}',
        "http://127.0.0.1:9",
        "passed",
    )
    return run_id


async def insert_run_with_scenario_without_steps(
    connection: asyncpg.Connection, fixture: Fixture
) -> uuid.UUID:
    run_id = await insert_run_without_scenarios(connection, fixture)
    await connection.execute(
        "INSERT INTO run_scenarios "
        "(id, run_id, source_scenario_id, scenario_key, name, risk_level, sort_order, status) "
        "VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)",
        uuid.uuid4(),
        run_id,
        fixture.scenario,
        "scenario_snapshot",
        '{"text":"empty scenario"}',
        "low",
        0,
        "pending",
    )
    return run_id


async def columns(connection: asyncpg.Connection, table: str) -> set[str]:
    rows = await connection.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1",
        table,
    )
    return {row["column_name"] for row in rows}


async def snapshot_versions(connection: asyncpg.Connection, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = await connection.fetch(
        "SELECT id, snapshot_version FROM test_runs WHERE id = ANY($1::uuid[])",
        ids,
    )
    return {row["id"]: row["snapshot_version"] for row in rows}


async def check(report: Report) -> None:
    await reset_scratch()
    try:
        previous = alembic("upgrade", PREVIOUS_REVISION)
        report.check("previous revision is reachable", previous.returncode == 0, previous.stderr[-400:])

        connection = await connect(SCRATCH_DB)
        try:
            fixture = await insert_fixture(connection)
            body_keys = ["request", "json_null", "empty_object", "empty_array", "extract"]

            complete = await insert_run(connection, fixture, name="complete", step_keys=body_keys)

            modified_fixture = await insert_fixture(connection)
            modified = await insert_run(
                connection, modified_fixture, name="modified", step_keys=["request"]
            )
            await connection.execute(
                "UPDATE test_steps SET updated_at = now() WHERE id = $1",
                modified_fixture.steps["request"],
            )

            missing_source = await insert_run(
                connection,
                fixture,
                name="missing-source",
                step_keys=["request"],
                source_step_override=None,
            )

            missing_scenario = await insert_run(
                connection, fixture, name="missing-scenario", step_keys=["request"]
            )
            await connection.execute(
                "UPDATE run_scenarios SET source_scenario_id = NULL WHERE run_id = $1",
                missing_scenario,
            )

            other_scenario = uuid.uuid4()
            await connection.execute(
                "INSERT INTO test_scenarios (id, plan_id, scenario_key, name) "
                "VALUES ($1, $2, $3, $4::jsonb)",
                other_scenario,
                fixture.plan,
                "scenario_other_" + uuid.uuid4().hex[:6],
                '{"text":"other"}',
            )
            other_step = uuid.uuid4()
            await connection.execute(
                "INSERT INTO test_steps "
                "(id, scenario_id, step_key, description, step_type, config, sort_order, "
                " created_at, updated_at) "
                "VALUES ($1, $2, $3, $4::jsonb, $5, $6::jsonb, $7, now() - interval '2 hours', "
                "        now() - interval '2 hours')",
                other_step,
                other_scenario,
                "request_other",
                '{"text":"other"}',
                "request",
                '{"method":"GET","path":"/other"}',
                0,
            )
            wrong_scenario = await insert_run(
                connection,
                fixture,
                name="wrong-scenario",
                step_keys=["request"],
                source_step_override=other_step,
            )

            no_scenarios = await insert_run_without_scenarios(connection, fixture)
            scenario_without_steps = await insert_run_with_scenario_without_steps(
                connection, fixture
            )

            historical_ids = [
                complete,
                modified,
                missing_source,
                missing_scenario,
                wrong_scenario,
                no_scenarios,
                scenario_without_steps,
            ]

            # Original rows that the migration must leave alone.
            await connection.execute(
                "INSERT INTO run_events (id, run_id, seq, event_type, payload) "
                "VALUES ($1, $2, 1, 'run.started', $3::jsonb)",
                uuid.uuid4(),
                complete,
                '{"startedAt":"2026-11-05T00:00:00Z"}',
            )
            await connection.execute(
                "INSERT INTO run_reports "
                "(id, project_id, run_id, name, filename, content_type, byte_size, sha256, content) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                uuid.uuid4(),
                fixture.project,
                complete,
                "report",
                "report.pdf",
                "application/pdf",
                7,
                "a" * 64,
                b"%PDF-1.4",
            )

            before_steps = await connection.fetchval(
                "SELECT count(*) FROM run_steps rs JOIN run_scenarios rsc ON rsc.id = rs.run_scenario_id "
                "WHERE rsc.run_id = $1",
                complete,
            )
            before_assertions = await connection.fetchval(
                "SELECT count(*) FROM run_assertions WHERE run_scenario_id IN "
                "(SELECT id FROM run_scenarios WHERE run_id = $1)",
                complete,
            )
            before_events = await connection.fetchval(
                "SELECT count(*) FROM run_events WHERE run_id = $1", complete
            )
            before_reports = await connection.fetchval(
                "SELECT count(*) FROM run_reports WHERE run_id = $1", complete
            )
            before_status = await connection.fetchval(
                "SELECT status FROM test_runs WHERE id = $1", complete
            )
            before_step_method = await connection.fetchval(
                "SELECT method FROM run_steps rs JOIN run_scenarios rsc ON rsc.id = rs.run_scenario_id "
                "WHERE rsc.run_id = $1 AND rs.step_key = 'request'",
                complete,
            )
        finally:
            await connection.close()

        upgraded = alembic("upgrade", "head")
        report.check("migration upgrades", upgraded.returncode == 0, upgraded.stderr[-500:])

        connection = await connect(SCRATCH_DB)
        try:
            report.check(
                "snapshot columns exist on run_steps",
                {"produces", "body", "body_present"} <= await columns(connection, "run_steps"),
            )
            report.check(
                "snapshot_version exists on test_runs",
                "snapshot_version" in await columns(connection, "test_runs"),
            )

            versions = await snapshot_versions(connection, historical_ids)
            report.check(
                "every pre-existing run is v0",
                all(version == 0 for version in versions.values()),
                versions,
            )

            for run_id, label in (
                (complete, "complete-looking tree"),
                (modified, "modified step"),
                (missing_source, "missing step source"),
                (missing_scenario, "missing scenario source"),
                (wrong_scenario, "wrong source scenario"),
                (no_scenarios, "run without scenarios"),
                (scenario_without_steps, "scenario without steps"),
            ):
                rows = await connection.fetch(
                    "SELECT rs.produces, rs.body, rs.body_present "
                    "FROM run_steps rs JOIN run_scenarios rsc ON rsc.id = rs.run_scenario_id "
                    "WHERE rsc.run_id = $1",
                    run_id,
                )
                report.check(
                    label + " is not backfilled",
                    all(
                        row["produces"] is None
                        and row["body"] is None
                        and row["body_present"] is False
                        for row in rows
                    ),
                    [dict(row) for row in rows],
                )

            report.equal(
                "run steps preserved",
                await connection.fetchval(
                    "SELECT count(*) FROM run_steps rs JOIN run_scenarios rsc ON rsc.id = rs.run_scenario_id "
                    "WHERE rsc.run_id = $1",
                    complete,
                ),
                before_steps,
            )
            report.equal(
                "run assertions preserved",
                await connection.fetchval(
                    "SELECT count(*) FROM run_assertions WHERE run_scenario_id IN "
                    "(SELECT id FROM run_scenarios WHERE run_id = $1)",
                    complete,
                ),
                before_assertions,
            )
            report.equal(
                "run events preserved",
                await connection.fetchval(
                    "SELECT count(*) FROM run_events WHERE run_id = $1", complete
                ),
                before_events,
            )
            report.equal(
                "run reports preserved",
                await connection.fetchval(
                    "SELECT count(*) FROM run_reports WHERE run_id = $1", complete
                ),
                before_reports,
            )
            report.equal(
                "run status preserved",
                await connection.fetchval(
                    "SELECT status FROM test_runs WHERE id = $1", complete
                ),
                before_status,
            )
            report.equal(
                "run step method preserved",
                await connection.fetchval(
                    "SELECT method FROM run_steps rs JOIN run_scenarios rsc ON rsc.id = rs.run_scenario_id "
                    "WHERE rsc.run_id = $1 AND rs.step_key = 'request'",
                    complete,
                ),
                before_step_method,
            )

            new_run = uuid.uuid4()
            await connection.execute(
                "INSERT INTO test_runs "
                "(id, project_id, plan_id, spec_id, plan_name, base_url, status) "
                "VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)",
                new_run,
                fixture.project,
                fixture.plan,
                fixture.spec,
                '{"text":"new run"}',
                "http://127.0.0.1:9",
                "queued",
            )
            report.equal(
                "a new run defaults to v1",
                await connection.fetchval(
                    "SELECT snapshot_version FROM test_runs WHERE id = $1", new_run
                ),
                1,
            )
        finally:
            await connection.close()

        down = alembic("downgrade", "-1")
        report.check("downgrade runs", down.returncode == 0, down.stderr[-500:])

        connection = await connect(SCRATCH_DB)
        try:
            report.check(
                "downgrade removes snapshot columns",
                "snapshot_version" not in await columns(connection, "test_runs")
                and "produces" not in await columns(connection, "run_steps"),
            )
        finally:
            await connection.close()

        back = alembic("upgrade", "head")
        report.check("upgrade after downgrade runs", back.returncode == 0, back.stderr[-500:])
    finally:
        await drop_scratch()


async def main() -> int:
    report = Report()
    await check(report)
    print("\n" + str(report.passed) + " passed, " + str(len(report.failures)) + " failed")
    for failure in report.failures:
        print("  - " + failure)
    return len(report.failures)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
