"""The stream, against a real HTTP server, while the run is still going.

C18 proved the frames of a *finished* run.  C19 tried to prove they arrive during a
run through httpx.ASGITransport and hung.  That hang was not the product: one process
hosted both the executor and the stream, so the stream request shared the engine pool
with the transaction the parked executor was holding.  This file moves the server into
its own process -- its own pool, its own loop -- and reads the stream with a real HTTP
client over a real socket, which is the path a browser takes.

The ordering is the claim: the client must have frames in hand *before* the parked
request is released.  Everything here is bounded, so a regression fails the test
instead of hanging the suite, and the server is always stopped.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import pytest
from sqlalchemy import select

from backend.db.models.project import Environment, Project
from backend.db.models.result import RunEvent
from backend.db.models.result import TestRun as _TestRun
from backend.db.models.user import GuestSession
from backend.schemas.run import RunCreateRequest
from backend.services import guest_session, run_executor, runs
from backend.services.guest_session import hash_token

from tests.test_run_execution import ENVIRONMENT_ID, _project_public_id, _run_body

pytestmark = pytest.mark.anyio

GUEST_HEADER = "X-Guest-Session"
BACKEND_DIR = Path(__file__).resolve().parents[1]
START_TIMEOUT = 45.0
HTTP_TIMEOUT = 30.0

FROZEN_EVENT_TYPES = frozenset(
    {
        "run.started",
        "step.started",
        "step.completed",
        "assertion.completed",
        "step.failed",
        "run.completed",
        "run.failed",
        "run.cancelled",
    }
)


def _free_port() -> int:
    """A port nothing is listening on, chosen by the OS and then released."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _real_client() -> httpx.AsyncClient:
    """A client with its own transport, so the executor client patch cannot touch it."""
    return httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(),
        timeout=httpx.Timeout(HTTP_TIMEOUT, read=HTTP_TIMEOUT),
        follow_redirects=False,
    )


class _ParkedClient(httpx.AsyncClient):
    """The executor client: answers from a script, parks on its first target request."""

    sent: list[httpx.Request] = []
    entered: asyncio.Event | None = None
    release: asyncio.Event | None = None
    parked: bool = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if "transport" not in kwargs:
            kwargs["transport"] = httpx.MockTransport(self._answer)
        super().__init__(*args, **kwargs)

    @property
    def _is_the_executors(self) -> bool:
        return isinstance(self._transport, httpx.MockTransport)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        raise AssertionError("the synchronous handler must not be used")

    async def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        if not self._is_the_executors:
            return await super().send(request, **kwargs)

        type(self).sent.append(request)
        if not type(self).parked:
            type(self).parked = True
            if type(self).entered is not None:
                type(self).entered.set()
            if type(self).release is not None:
                await type(self).release.wait()

        if request.method == "GET" and request.url.path == "/orders/order_1":
            return httpx.Response(200, json={"orderId": "order_1", "status": "open"})
        if request.method == "POST" and request.url.path == "/orders":
            return httpx.Response(201, json={"id": "order_2"})
        return httpx.Response(404, json={"error": "unexpected target"})


def _install_parked_client(monkeypatch, *, entered, release) -> type[_ParkedClient]:
    _ParkedClient.sent = []
    _ParkedClient.entered = entered
    _ParkedClient.release = release
    _ParkedClient.parked = False
    monkeypatch.setattr(httpx, "AsyncClient", _ParkedClient)
    return _ParkedClient


async def _seed_owner(fixtures, stack) -> tuple[str, uuid.UUID]:
    token = guest_session.generate_token()
    now = datetime.now(timezone.utc)
    guest = GuestSession(
        token_hash=hash_token(token),
        created_at=now,
        expires_at=now + timedelta(days=1),
        last_seen_at=now,
        revoked_at=None,
    )
    fixtures.session.add(guest)
    await fixtures._keep(GuestSession, guest)

    project = Project(
        guest_session_id=guest.id,
        public_id="c20prj_" + uuid.uuid4().hex[:12],
        name="C20 live server project",
        description="Created by backend/tests; deleted by its own cleanup.",
    )
    fixtures.session.add(project)
    await fixtures._keep(Project, project)

    environment = Environment(
        project_id=project.id,
        public_id=ENVIRONMENT_ID,
        name="C20 live environment",
        kind="development",
        base_url="http://127.0.0.1:9",
    )
    fixtures.session.add(environment)
    await fixtures._keep(Environment, environment)
    await fixtures.commit()
    return token, project.id


async def _create_run(fixtures, project_id: uuid.UUID, monkeypatch):
    public_id = await _project_public_id(fixtures, project_id)

    async def _do_not_schedule(run_id):
        return None

    monkeypatch.setattr(run_executor, "schedule_run", _do_not_schedule)
    response = await runs.create_run(
        fixtures.session,
        project_id=public_id,
        payload=RunCreateRequest.model_validate(_run_body(public_id)),
    )
    return uuid.UUID(str(response.id))


async def _event_rows(session, run_id: uuid.UUID) -> list[RunEvent]:
    return list(
        (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
            )
        ).scalars()
    )


def _parse_sse_frames(text: str) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for block in text.split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if line.startswith(":") or not line:
                continue
            name, _, value = line.partition(": ")
            fields[name] = value
        if "data" in fields:
            frames.append(
                {
                    "id": int(fields["id"]),
                    "event": fields["event"],
                    "data": json.loads(fields["data"]),
                }
            )
    return frames


@pytest.fixture
async def live_server() -> AsyncIterator[str]:
    """A real uvicorn process on a loopback port, always stopped afterwards."""
    port = _free_port()
    env = dict(os.environ)
    # Set before the app imports, and dotenv does not override an existing variable,
    # so the server cannot end up pointed at the development database.
    env["POSTGRES_DB"] = "aiata_c4_test"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    base = f"http://127.0.0.1:{port}"
    try:
        deadline = asyncio.get_running_loop().time() + START_TIMEOUT
        async with _real_client() as client:
            while True:
                if proc.poll() is not None:
                    raise AssertionError(
                        f"the server exited before it was ready (rc={proc.returncode})"
                    )
                try:
                    response = await client.get(base + "/api/does-not-exist")
                    if response.status_code in (401, 404):
                        break
                except httpx.HTTPError:
                    pass
                if asyncio.get_running_loop().time() > deadline:
                    raise AssertionError("the server did not become ready in time")
                await asyncio.sleep(0.2)
        yield base
    finally:
        proc.terminate()
        try:
            await asyncio.get_running_loop().run_in_executor(None, proc.wait, 15)
        except Exception:
            proc.kill()
        if proc.poll() is None:
            proc.kill()


async def test_frames_arrive_from_a_real_server_before_the_request_is_released(
    fixtures, stack, read_session, monkeypatch, live_server
) -> None:
    """The live proof: frames are in the client hand while the run is parked.

    Create the run, open the stream over a real socket, start the executor, let it
    park on its first request, read until two frames arrive, and only then release.
    A buffered response could not satisfy this: there would be nothing to read until
    the run ended, and the release would still be unset.
    """
    token, project_id = await _seed_owner(fixtures, stack)

    entered = asyncio.Event()
    release = asyncio.Event()
    client_type = _install_parked_client(monkeypatch, entered=entered, release=release)

    run_id = await _create_run(fixtures, project_id, monkeypatch)

    received: list[dict[str, Any]] = []
    frames_before_release: list[int] = []
    task: asyncio.Task | None = None

    async with _real_client() as client:
        try:
            async with client.stream(
                "GET",
                f"{live_server}/api/runs/{run_id}/events/stream",
                headers={GUEST_HEADER: token},
            ) as response:
                assert response.status_code == 200, await response.aread()
                assert response.headers["content-type"].startswith("text/event-stream")

                task = asyncio.create_task(run_executor.execute_run(run_id))
                run_executor._RUNNING_TASKS[run_id] = task
                task.add_done_callback(
                    lambda finished, key=run_id: run_executor._forget(key, finished)
                )

                stream = response.aiter_text()
                buffer = ""
                while len(received) < 2:
                    chunk = await asyncio.wait_for(anext(stream), timeout=HTTP_TIMEOUT)
                    buffer += chunk
                    received.extend(
                        frame for frame in _parse_sse_frames(buffer) if frame not in received
                    )

                # The proof: two frames in hand, and the request is still parked.
                frames_before_release.append(len(received))
                assert release.is_set() is False, "frames were only read after the release"
                assert task.done() is False, "the run had already finished"

                status = (
                    await read_session.execute(
                        select(_TestRun.status).where(_TestRun.id == run_id)
                    )
                ).scalar_one()
                assert status == "running"
                assert client_type.parked is True, "the executor was not parked"
                assert len(client_type.sent) == 1

                release.set()
                await asyncio.wait_for(task, timeout=HTTP_TIMEOUT)

                while True:
                    try:
                        chunk = await asyncio.wait_for(anext(stream), timeout=HTTP_TIMEOUT)
                    except StopAsyncIteration:
                        break
                    buffer += chunk
                    received.extend(
                        frame for frame in _parse_sse_frames(buffer) if frame not in received
                    )
        finally:
            release.set()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            run_executor._RUNNING_TASKS.pop(run_id, None)

    assert frames_before_release == [2]
    assert [frame["event"] for frame in received[:2]] == ["run.started", "step.started"]
    assert [frame["id"] for frame in received[:2]] == [1, 2]

    read_session.expire_all()
    stored = await _event_rows(read_session, run_id)
    assert [frame["id"] for frame in received] == [event.seq for event in stored], (
        "the frames delivered over HTTP do not match the persisted history"
    )
    assert [frame["event"] for frame in received] == [
        event.event_type for event in stored
    ]
    assert received[-1]["event"] == "run.completed"
    assert [event.seq for event in stored] == list(range(1, len(stored) + 1))
    assert set(event.event_type for event in stored) <= FROZEN_EVENT_TYPES

    finished = (
        await read_session.execute(select(_TestRun.status).where(_TestRun.id == run_id))
    ).scalar_one()
    assert finished == "passed"
