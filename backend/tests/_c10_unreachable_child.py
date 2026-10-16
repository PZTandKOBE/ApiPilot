"""Child process for the T9 startup check.  Run by test_run_recovery_startup.py.

Reads POSTGRES_* from the environment before importing anything from backend, so the
module-level engine really points at the unreachable port.  Prints one JSON line and
nothing else about credentials.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend  # noqa: F401  (the installed package wins; the fallback is above)
from backend.app import create_app  # noqa: E402
from backend.db import database  # noqa: E402
from backend.services import run_executor  # noqa: E402


class _Collector(logging.Handler):
    """Remembers whether recovery said it could not reach the database.

    Only a boolean leaves this process: the record text can contain a traceback, and a
    traceback can contain the connection URL.
    """

    def __init__(self) -> None:
        super().__init__()
        self.recovery_failed = False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            return
        if "run recovery" in message and "could not be listed" in message:
            self.recovery_failed = True


async def main() -> int:
    collector = _Collector()
    executor_logger = logging.getLogger("backend.services.run_executor")
    executor_logger.addHandler(collector)
    executor_logger.setLevel(logging.INFO)

    expected_port = int(os.environ["C10_EXPECTED_PORT"])
    verdict: dict[str, object] = {
        "resolved_database": database.database_url.database,
        "resolved_port": database.database_url.port,
        "resolved_host": database.database_url.host,
        "executor_disabled": bool(os.environ.get(run_executor.EXECUTOR_DISABLED_ENV)),
        "expected_port_matches": database.database_url.port == expected_port,
    }

    counts = await run_executor.recover_queued_runs()
    verdict["recovery_returned_empty"] = counts == {}
    verdict["recovery_logged_failure"] = collector.recovery_failed

    app = create_app()
    verdict["app_constructed"] = app is not None

    reached = False
    async with app.router.lifespan_context(app):
        # Reaching this line is the claim: startup ran and did not abort.
        reached = True
    verdict["reached_running_phase"] = reached
    verdict["recovery_logged_failure_after_lifespan"] = collector.recovery_failed

    print("C10-VERDICT " + json.dumps(verdict, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
