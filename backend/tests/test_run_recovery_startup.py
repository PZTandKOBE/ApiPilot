"""Startup behaviour when the database is unreachable: no app, no session.

This file deliberately does not touch the shared fixtures.  The objects it would have to
change -- ``database_url``, ``engine``, ``AsyncSessionLocal`` -- are built at import time
in ``backend.db.database``, so a parent process that has already imported the backend
cannot re-point them by editing the environment.  Instead the check runs in a fresh
interpreter: the child sets POSTGRES_* before importing anything, drives the real
lifespan and reports a small JSON verdict.

The port it points at is chosen and proven unreachable before the child starts.  No
database is created, migrated or written, and the development database is never named.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
CHILD_SCRIPT = Path(__file__).resolve().parent / "_c10_unreachable_child.py"
SCRATCH_DB = "aiata_c4_test"


def _free_port() -> int:
    """Ask the OS for an unused port, then make sure nothing answers on it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(1.0)
    try:
        connected = probe.connect_ex(("127.0.0.1", port)) == 0
    finally:
        probe.close()
    if connected:
        raise AssertionError(f"port {port} accepted a connection; pick another")
    return port


def test_t9_unreachable_database_does_not_stop_startup(tmp_path) -> None:
    """Recovery fails loudly and the lifespan still reaches its running phase.

    Two things have to be true at once, and each one alone would be a weaker test: the
    recovery path must really have tried to reach the database (otherwise "the app
    started" says nothing), and the failure must not have escaped into the lifespan.
    """
    port = _free_port()
    if port == 5432:
        raise AssertionError("the probe returned the PostgreSQL port; refusing to run")

    # An empty .env in the working directory: load_dotenv() then finds nothing to
    # override the child environment with.  Nothing is written inside the repository.
    (tmp_path / ".env").write_text("", encoding="utf-8")

    child_env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": os.environ.get("TEMP", str(tmp_path)),
        "TMP": os.environ.get("TMP", str(tmp_path)),
        "PYTHONIOENCODING": "utf-8",
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": str(port),
        "POSTGRES_DB": SCRATCH_DB,
        "POSTGRES_USER": "c10_probe_user",
        "POSTGRES_PASSWORD": "c10-not-a-real-credential",
        "C10_EXPECTED_PORT": str(port),
    }
    child_env.pop("RUN_EXECUTOR_DISABLED", None)

    completed = subprocess.run(
        [sys.executable, str(CHILD_SCRIPT)],
        cwd=str(tmp_path),
        env=child_env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    marker = "C10-VERDICT "
    verdict_line = next(
        (line for line in completed.stdout.splitlines() if line.startswith(marker)),
        None,
    )
    if verdict_line is None:
        raise AssertionError(
            "the child produced no verdict; exit="
            f"{completed.returncode} stdout tail={completed.stdout[-600:]!r} "
            f"stderr tail={completed.stderr[-600:]!r}"
        )

    verdict = json.loads(verdict_line[len(marker):])
    if completed.returncode != 0:
        raise AssertionError(f"the child exited {completed.returncode}: {verdict!r}")

    if verdict["resolved_database"] != SCRATCH_DB:
        raise AssertionError(f"child resolved the wrong database: {verdict!r}")
    if verdict["resolved_port"] != port:
        raise AssertionError(f"child resolved the wrong port: {verdict!r}")
    if verdict["executor_disabled"]:
        raise AssertionError("RUN_EXECUTOR_DISABLED was set; the skip would be trivial")

    if not verdict["recovery_logged_failure"]:
        raise AssertionError(
            "recovery never reported a database failure, so it did not really try"
        )
    if not verdict["recovery_returned_empty"]:
        raise AssertionError("recovery reported work despite having no database")
    if not verdict["reached_running_phase"]:
        raise AssertionError("the lifespan never reached its running phase")
    if verdict["app_constructed"] is not True:
        raise AssertionError("create_app() did not return an application")
