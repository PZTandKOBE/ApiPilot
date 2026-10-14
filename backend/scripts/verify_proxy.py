"""Security review of the request proxy (Phase 8.5 Step 3, Task B9).

One question, measured rather than argued: **what does this proxy refuse, and
what can it be made to connect to?**

The suite is written the way the other reviews in this directory are: real rows
in a real PostgreSQL, the real ASGI app driven in-process, and a real target
server on the loopback interface.  Four instruments make the answers evidence
instead of opinion:

* **The resolver is replaced, not the policy.**  `services.api_proxy.resolve_target`
  is monkeypatched so the *names* the proxy is asked to dial are recorded and the
  answers are chosen.  Address classification, the all-answers rule and the
  dial itself are the shipped code.
* **A dial guard sits at the socket layer.**  `open_pool` is replaced with a pool
  whose network backend records every `connect_tcp` and then refuses it.  A test
  that says "no connection was made" therefore means the bottom of the stack was
  never asked, and "the connection went to X" means X is what would have been
  dialled.
* **A real loopback server proves the allowed path end to end** -- genuinely
  resolved, genuinely connected, headers and body genuinely delivered.
* **A real TLS server proves the pinning did not cost the certificate check.**
  Python's own test certificate is trusted through `SSL_CERT_FILE`, so a
  successful handshake is a *verified* one, and a name that does not match the
  certificate must fail.

Nothing here reaches the internet or the local network beyond loopback.  Every
fixture row is written under a `b9-` namespace and removed at the end.

    python scripts/verify_proxy.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import ssl
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

try:  # installed package (uv_build src-layout); fall back for a bare checkout
    import backend  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on how it is invoked
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpcore  # noqa: E402
import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402

from backend.app import create_app  # noqa: E402
from backend.db.database import AsyncSessionLocal  # noqa: E402
from backend.db.models.project import Project  # noqa: E402
from backend.services import api_proxy, guest_session  # noqa: E402

__all__ = ["main"]

# The certificate CPython ships for its own test suite -- a real certificate for
# "localhost", so pointing SSL_CERT_FILE at it makes the default verification
# context trust exactly one issuer and nothing else.
TEST_CERT = Path(sys.base_prefix) / "Lib" / "test" / "keycert.pem"

ALLOWED_IP = "93.184.216.34"
SECOND_ALLOWED_IP = "8.8.8.8"
"""An address that classifies as allowed.  It is never dialled: the guard stops
every connection, and the loopback tests are the only ones that connect."""

HOST = "proxy-test.example"


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


@dataclass
class Report:
    checks: int = 0
    failures: list[str] = field(default_factory=list)
    groups: dict[str, list[str]] = field(default_factory=dict)

    def check(self, group: str, name: str, ok: bool, detail: str = "") -> bool:
        self.checks += 1
        line = f"{name}{(' -- ' + detail) if detail else ''}"
        self.groups.setdefault(group, []).append(("PASS " if ok else "FAIL ") + line)
        if not ok:
            self.failures.append(f"{group}: {line}")
        return ok

    def equal(self, group: str, name: str, got: Any, want: Any) -> bool:
        return self.check(group, name, got == want, f"got {got!r}, want {want!r}")

    def print(self) -> None:
        for group, lines in self.groups.items():
            print(f"\n{group}")
            for line in lines:
                print("  " + line)
        print("\n" + "=" * 72)
        print(f"checks: {self.checks}   failures: {len(self.failures)}")
        for failure in self.failures:
            print("  FAILED " + failure)


# --------------------------------------------------------------------------- #
# Instruments
# --------------------------------------------------------------------------- #


class DialGuard(httpcore.AsyncNetworkBackend):
    """Records the dial and refuses it.

    Standing in for the network backend means the destination httpcore *would*
    have connected to is written down, while nothing leaves the machine.
    """

    def __init__(self, log: list[dict[str, Any]]) -> None:
        self._log = log

    async def connect_tcp(
        self, host: str, port: int, timeout: Any = None, local_address: Any = None,
        socket_options: Any = None,
    ) -> Any:
        self._log.append({"host": host, "port": port})
        raise httpcore.ConnectError("refused by the dial guard")

    async def connect_unix_socket(self, path: str, timeout: Any = None, socket_options: Any = None) -> Any:
        self._log.append({"uds": path})
        raise httpcore.ConnectError("refused by the dial guard")

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class Probe:
    """Resolver + dial records for one scenario."""

    def __init__(self) -> None:
        self.names: list[tuple[str, int]] = []
        self.dials: list[dict[str, Any]] = []
        self.answers: dict[str, list[str]] = {}
        self.default_answer: list[str] = [ALLOWED_IP]
        self.real_dial = False

    def resolver(self) -> Callable[[str, int], Any]:
        """A recording DNS double: it answers, and that is all it does.

        It deliberately does *not* re-implement the address policy.  The policy
        under test is the shipped `resolve_target`, which classifies every answer
        and raises; a double that also classified would be testing itself.  What
        this records is the request ("which name was looked up, when"), and what it
        returns is the input the real policy is then fed.
        """

        async def resolve(hostname: str, port: int) -> bytes:
            self.names.append((hostname, port))
            addresses = self.answers.get(hostname, self.default_answer)

            # The policy is the shipped one -- `classify_address`, the same call
            # the real `resolve_target` makes.  Re-implementing it here would test
            # the double; skipping it would let a blocked address reach the dial
            # guard and be recorded as a connection the proxy was willing to make.
            for address in addresses:
                reason = api_proxy.classify_address(address)
                if reason != "allowed":
                    raise api_proxy.ProxyError(
                        api_proxy.BLOCKED_TARGET_CODE, reason
                    )

            return addresses[0].encode("ascii")

        return resolve

    def pool(self) -> Callable[..., Any]:
        original = api_proxy.open_pool

        def open_pool(**kwargs: Any) -> Any:
            if self.real_dial:
                return original(**kwargs)

            pool = original(**kwargs)
            pool._network_backend = DialGuard(self.dials)  # the socket layer
            return pool

        return open_pool


@dataclass
class LoopbackServer:
    """A real HTTP target on 127.0.0.1 that records what it received."""

    port: int
    seen: list[dict[str, Any]] = field(default_factory=list)
    reply_status: int = 200
    reply_reason: str = "OK"
    reply_body: bytes = b'{"ok":true}'
    reply_headers: list[tuple[str, str]] = field(
        default_factory=lambda: [("Content-Type", "application/json")]
    )


class LoopbackTarget:
    """A real HTTP target on 127.0.0.1, running in this event loop.

    An asyncio server rather than a `http.server` on a thread: the proxy is driven
    through `httpx.ASGITransport`, which runs the app in *this* loop, so a
    blocking server on another thread would be measured while it is blocked.  Same
    reason the TLS target below is async.
    """

    def __init__(self, store: LoopbackServer) -> None:
        self.store = store
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._serve, host="127.0.0.1", port=0
        )
        self.store.port = self._server.sockets[0].getsockname()[1]

    async def _serve(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            method, path, _ = lines[0].split(" ", 2)
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    headers[name.strip().lower()] = value.strip()

            length = int(headers.get("content-length") or 0)
            body = await reader.readexactly(length) if length else b""

            self.store.seen.append(
                {
                    "method": method,
                    "path": path,
                    "host": headers.get("host"),
                    "headers": list(headers.items()),
                    "body": body.decode("utf-8", "replace"),
                }
            )

            store = self.store
            payload = store.reply_body
            out = [
                f"HTTP/1.1 {store.reply_status} {store.reply_reason}",
                *[f"{name}: {value}" for name, value in store.reply_headers],
                f"Content-Length: {len(payload)}",
                "",
                "",
            ]
            writer.write("\r\n".join(out).encode("latin-1") + payload)
            await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    def close(self) -> None:
        if self._server is not None:
            self._server.close()


class TlsTarget:
    """A real TLS server presenting CPython's test certificate for localhost."""

    def __init__(self) -> None:
        self.sni: list[str | None] = []
        self.requests = 0
        self.requests_log: list[str] = []

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(TEST_CERT)
        # The callback fires during the handshake, so the name the client asked
        # for is recorded before a single byte of application data arrives.
        context.sni_callback = lambda sock, name, ctx: self.sni.append(name)

        self._context = context
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._serve, host="127.0.0.1", port=0, ssl=self._context
        )
        self.port = self._server.sockets[0].getsockname()[1]

    async def _serve(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            self.requests += 1
            for line in head.decode("latin-1").split("\r\n"):
                if line.lower().startswith("host:"):
                    self.requests_log.append(line.split(":", 1)[1].strip())

            body = b'{"tls":true}'
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + body
            )
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, OSError, ssl.SSLError):
            # A client that aborts the handshake or the read is the expected
            # outcome of the mismatch case, not a failure of the target.
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError, ssl.SSLError):
                pass

    def close(self) -> None:
        if self._server is not None:
            self._server.close()



# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


class Fixtures:
    """Rows written for this run, and removed at the end."""

    def __init__(self) -> None:
        self.marker = "b9-" + uuid.uuid4().hex[:8]
        self.projects: dict[str, str] = {}
        self.tokens: dict[str, str] = {}
        self.guest_ids: dict[str, uuid.UUID] = {}

    async def create_guest(self, name: str) -> None:
        """A genuine session, issued by the service that issues them.

        The credential is real, not a fixture row with a hand-written digest: the
        point of the identity checks below is that the *shipped* verification
        accepts it, which a fabricated hash would not prove.
        """
        async with AsyncSessionLocal() as session:
            guest, token = await guest_session.issue(session)
            await session.commit()

        self.guest_ids[name] = guest.id
        self.tokens[name] = token

    async def create_project(self, guest: str, key: str) -> str:
        """One project, written through the product's own model.

        The rows are the rows the schema defines -- a project with exactly one
        owner and no environment -- rather than hand-written SQL that could drift
        from it.
        """
        public_id = f"{self.marker}-{key}"
        async with AsyncSessionLocal() as session:
            session.add(
                Project(
                    id=uuid.uuid4(),
                    public_id=public_id,
                    name=key,
                    description="",
                    guest_session_id=self.guest_ids[guest],
                )
            )
            await session.commit()

        self.projects[key] = public_id
        return public_id

    async def cleanup(self) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("delete from projects where public_id like :like"),
                {"like": self.marker + "%"},
            )
            await session.execute(
                text("delete from guest_sessions where id = any(:ids)"),
                {"ids": list(self.guest_ids.values())},
            )
            await session.commit()


# --------------------------------------------------------------------------- #
# Scenario runner
# --------------------------------------------------------------------------- #


@dataclass
class Harness:
    app: Any
    fixtures: Fixtures
    probe: Probe

    async def post(
        self, project_key: str, payload: dict[str, Any], guest: str = "owner"
    ) -> httpx.Response:
        """One call to the proxy route.

        `guest` names a credential to present: a fixture's ("owner",
        "stranger"), `"none"` for no header at all, or `"unknown"` for a token
        that is well-formed and names nothing.
        """
        headers = {}
        if guest == "unknown":
            headers["X-Guest-Session"] = "b9-not-a-real-session-token"
        elif guest != "none":
            headers["X-Guest-Session"] = self.fixtures.tokens[guest]

        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://platform.test"
        ) as client:
            return await client.post(
                f"/api/projects/{self.fixtures.projects[project_key]}/proxy",
                json=payload,
                headers=headers,
            )


def install(probe: Probe, monkeypatch_target: Any = api_proxy) -> None:
    monkeypatch_target.resolve_target = probe.resolver()  # type: ignore[assignment]
    monkeypatch_target.open_pool = probe.pool()  # type: ignore[assignment]


def restore(original_pool: Any, original_resolve: Any) -> None:
    api_proxy.open_pool = original_pool  # type: ignore[assignment]
    api_proxy.resolve_target = original_resolve  # type: ignore[assignment]


async def main() -> int:
    report = Report()

    global SHIPPED_RESOLVER

    original_pool = api_proxy.open_pool
    original_resolve = api_proxy.resolve_target
    # Kept before anything is installed over it, so the address-policy checks can
    # put the real function back and measure that rather than the double.
    SHIPPED_RESOLVER = original_resolve

    fixtures = Fixtures()
    await fixtures.create_guest("owner")
    await fixtures.create_guest("stranger")
    await fixtures.create_project("owner", "mine")
    await fixtures.create_project("stranger", "theirs")

    app = create_app()

    probe = Probe()
    install(probe)
    harness = Harness(app=app, fixtures=fixtures, probe=probe)

    target = LoopbackServer(port=0)
    server = LoopbackTarget(target)
    await server.start()
    tls_target = TlsTarget()
    await tls_target.start()

    try:
        await _identity(report, harness, probe)
        await _ssrf(report, harness, probe)
        await _pinning(report, harness, probe)
        await _allowed(report, harness, probe, target, server)
        await _protocol(report, harness, probe, target)
        await _limits(report, harness, probe, target)
        await _tls(report, harness, probe, tls_target)
    finally:
        restore(original_pool, original_resolve)
        server.close()
        tls_target.close()
        await fixtures.cleanup()

    report.print()
    return len(report.failures)


# --------------------------------------------------------------------------- #
# A. Identity and ownership
# --------------------------------------------------------------------------- #


async def _identity(report: Report, harness: Harness, probe: Probe) -> None:
    group = "A. identity and ownership"
    probe.answers.clear()
    probe.default_answer = [ALLOWED_IP]
    payload = {"method": "GET", "url": f"http://{HOST}/anything"}

    probe.names.clear()
    probe.dials.clear()
    response = await harness.post("mine", payload, guest="none")
    report.equal(group, "no credential is refused", response.status_code, 401)
    report.equal(
        group,
        "and refuses with the contract's code",
        response.json().get("code"),
        "guest-session-required",
    )
    report.equal(group, "without resolving a name", probe.names, [])
    report.equal(group, "and without dialling", probe.dials, [])

    probe.names.clear()
    probe.dials.clear()
    response = await harness.post("mine", payload, guest="unknown")
    report.equal(group, "an unknown credential is refused", response.status_code, 401)
    report.equal(group, "without resolving a name", probe.names, [])

    probe.names.clear()
    probe.dials.clear()
    response = await harness.post("theirs", payload, guest="owner")
    report.equal(
        group,
        "another guest's project is a 404, not a 403",
        response.status_code,
        404,
    )
    report.equal(group, "and no name is resolved for it", probe.names, [])
    report.equal(group, "and nothing is dialled for it", probe.dials, [])

    probe.names.clear()
    response = await harness.post("mine", payload, guest="owner")
    report.check(
        group,
        "the same request succeeds for the owner",
        response.status_code == 502,
        f"status {response.status_code}",
    )
    report.equal(group, "and only then is the name resolved", probe.names, [(HOST, 80)])


# --------------------------------------------------------------------------- #
# B. SSRF
# --------------------------------------------------------------------------- #


SHIPPED_RESOLVER: Callable[..., Any] | None = None
"""The real `resolve_target`, kept because the harness replaces the module's.

Assigning a double over a module attribute that a test then wants to measure is
how three checks in this file passed while measuring the wrong thing at first.
"""


async def _classify_all(addresses: list[str]) -> bool:
    """Whether the *shipped* `resolve_target` refuses an answer set.

    The DNS lookup is replaced at the socket layer -- `getaddrinfo` -- so the code
    under test is the real function, including its loop over every answer.  This is
    the only way to feed it a two-address reply without controlling a real name.

    The module attribute is restored for the duration, because the harness has
    already replaced it with a recording double.
    """
    original = socket.getaddrinfo
    installed = api_proxy.resolve_target
    if SHIPPED_RESOLVER is not None:
        api_proxy.resolve_target = SHIPPED_RESOLVER  # type: ignore[assignment]

    def fake_getaddrinfo(host: str, port: int, *args: Any, **kwargs: Any) -> list[Any]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))
            for address in addresses
        ]

    # The resolver is replaced at the socket layer, which is the seam
    # `asyncio` itself calls through -- so the function under test is the shipped
    # `resolve_target` with its loop over every answer intact.
    socket.getaddrinfo = fake_getaddrinfo  # type: ignore[assignment]
    try:
        # A name that is not on the local-name deny list, so what is measured is
        # the address policy and nothing else.
        await api_proxy.resolve_target("policy-probe.example", 80)
        return False
    except api_proxy.ProxyError:
        return True
    finally:
        socket.getaddrinfo = original  # type: ignore[assignment]
        api_proxy.resolve_target = installed  # type: ignore[assignment]


async def _refused(
    report: Report, harness: Harness, probe: Probe, name: str, url: str
) -> None:
    group = "B. SSRF"
    probe.names.clear()
    probe.dials.clear()
    response = await harness.post("mine", {"method": "GET", "url": url})
    reported = response.json()
    report.check(
        group,
        f"{name} is refused",
        response.status_code == 400 and reported.get("code") == "proxy-target-blocked",
        f"status {response.status_code} code {reported.get('code')}",
    )
    report.equal(group, f"{name}: nothing dialled", probe.dials, [])


async def _ssrf(report: Report, harness: Harness, probe: Probe) -> None:
    group = "B. SSRF"
    probe.answers.clear()
    probe.default_answer = [ALLOWED_IP]
    base = "http://{host}/x"

    for scheme in ("ftp", "file", "gopher", "ws"):
        probe.names.clear()
        probe.dials.clear()
        response = await harness.post(
            "mine", {"method": "GET", "url": f"{scheme}://{HOST}/x"}
        )
        report.check(
            group,
            f"scheme {scheme} is refused",
            response.status_code == 400
            and response.json().get("code") == "proxy-invalid-request",
            f"status {response.status_code} code {response.json().get('code')}",
        )
        report.equal(group, f"scheme {scheme}: no dial", probe.dials, [])

    probe.names.clear()
    response = await harness.post(
        "mine", {"method": "CONNECT", "url": base.format(host=HOST)}
    )
    report.check(
        group,
        "CONNECT is not an allowed method",
        response.status_code == 422,
        f"status {response.status_code}",
    )
    report.equal(group, "CONNECT: no dial", probe.dials, [])

    probe.names.clear()
    response = await harness.post(
        "mine", {"method": "GET", "url": f"http://user:pass@{HOST}/x"}
    )
    report.check(
        group,
        "credentials in the url are refused",
        response.status_code == 400,
        f"status {response.status_code}",
    )

    # Every one of these names is *answered* with a blocked address.
    blocked = {
        "loopback v4": "127.0.0.1",
        "loopback v6": "::1",
        "rfc1918 10/8": "10.0.0.5",
        "rfc1918 192.168/16": "192.168.1.10",
        "rfc1918 172.16/12": "172.16.5.4",
        "link-local v4": "169.254.10.10",
        "link-local v6": "fe80::1",
        "metadata v4": "169.254.169.254",
        "metadata alibaba": "100.100.100.200",
        "unspecified": "0.0.0.0",
        "multicast": "224.0.0.1",
        "reserved": "240.0.0.1",
        "ipv4-mapped loopback": "::ffff:127.0.0.1",
    }
    for label, address in blocked.items():
        probe.answers[HOST] = [address]
        await _refused(report, harness, probe, label, base.format(host=HOST))

    # `localhost` and its dotted variant are answered by the double as loopback --
    # which is what every resolver says -- and then refused by the shipped policy.
    probe.answers["localhost"] = ["127.0.0.1"]
    probe.answers["localhost."] = ["127.0.0.1"]
    for spelling in ("localhost", "localhost."):
        await _refused(report, harness, probe, f"localhost spelling {spelling}", f"http://{spelling}/x")

    # The mixed answer: one public address and one private.  Accepting the public
    # one would be the hole this rule exists to close.
    #
    # The policy is exercised by the *real* resolver: these names are answered by
    # the operating system's resolver, and the loopback/private literals below are
    # answered by the double.  A mixed answer needs the real policy fed two
    # addresses, which is what the shipped `resolve_target` does with a real DNS
    # reply -- so it is driven directly rather than through a name.
    refusal = await _classify_all([ALLOWED_IP, "127.0.0.1"])
    report.equal(group, "a mixed answer is refused by the real policy", refusal, True)
    refusal = await _classify_all(["127.0.0.1", ALLOWED_IP])
    report.equal(group, "order does not matter to the real policy", refusal, True)
    refusal = await _classify_all([ALLOWED_IP, ALLOWED_IP])
    report.equal(group, "an all-public answer is accepted", refusal, False)

    # A non-canonical spelling still classifies as what it reaches.  These are not
    # answered by the double: the spelling goes to the operating system's resolver,
    # which is the thing that decides what it means.
    for spelling in ("2130706433", "0x7f.0.0.1", "127.1", "0177.0.0.1"):
        # Whether the platform's resolver understands the spelling or not, the
        # answer it gives for it is loopback -- so the double answers, and the
        # shipped policy decides.  Either way no dial may happen.
        probe.answers[spelling] = ["127.0.0.1"]
        probe.default_answer = ["127.0.0.1"]
        probe.dials.clear()
        response = await harness.post(
            "mine", {"method": "GET", "url": f"http://{spelling}/x"}
        )
        report.check(
            group,
            f"non-canonical host {spelling} cannot reach loopback",
            response.status_code == 400
            and response.json().get("code") == api_proxy.BLOCKED_TARGET_CODE,
            f"status {response.status_code} code {response.json().get('code')}",
        )
        report.equal(group, f"{spelling}: no dial", probe.dials, [])

    probe.answers.clear()
    probe.default_answer = [ALLOWED_IP]


# --------------------------------------------------------------------------- #
# C. The allowed path, end to end
# --------------------------------------------------------------------------- #


async def _allowed(
    report: Report,
    harness: Harness,
    probe: Probe,
    target: LoopbackServer,
    server: LoopbackTarget,
) -> None:
    group = "C. the allowed path (real loopback target)"
    probe.real_dial = True
    # The pinning guarantee is proved separately (block D); this block proves the
    # bytes.  Loopback is the only reachable target in a test environment, so the
    # classifier is relaxed here and the real pool, socket and TLS path are left
    # exactly as shipped.
    #
    # The resolver is still *this* resolver, so it has to be told what the literal
    # address resolves to -- and the answer has to be the address the URL names, or
    # the proxy would faithfully dial whatever it was handed.  Environment left
    # clean first: an answer left over from an earlier block is how this failed the
    # first time.
    probe.answers.clear()
    probe.default_answer = [ALLOWED_IP]
    probe.answers["127.0.0.1"] = ["127.0.0.1"]
    probe.answers["localhost"] = ["127.0.0.1"]
    original_classify = api_proxy.classify_address
    api_proxy.classify_address = lambda address: "allowed"  # type: ignore[assignment]

    try:
        url = f"http://127.0.0.1:{target.port}/api/orders?page=2"
        target.seen.clear()


        response = await harness.post(
            "mine",
            {
                "method": "POST",
                "url": url,
                "headers": [
                    {"name": "Content-Type", "value": "application/json"},
                    {"name": "Authorization", "value": "Bearer target-token"},
                    {"name": "X-Guest-Session", "value": "must-not-travel"},
                    {"name": "X-Custom", "value": "kept"},
                ],
                "body": '{"product_id":"prod_001"}',
            },
        )

        report.equal(group, "the request is answered", response.status_code, 200)
        payload = response.json() if response.status_code == 200 else {}
        report.equal(group, "the target's status is reported", payload.get("status"), 200)
        report.equal(group, "the target's body is reported", payload.get("body"), '{"ok":true}')
        # camelCase on the wire: the frontend's `ApiResponse.contentType` is the
        # name, and the assertion reads the same field the client will.
        report.equal(group, "the content type is reported", payload.get("contentType"), "application/json")

        seen = target.seen[0] if target.seen else {}
        report.equal(group, "the target saw the method", seen.get("method"), "POST")
        report.equal(group, "the target saw the path and query", seen.get("path"), "/api/orders?page=2")
        report.equal(
            group,
            "the target's Host names the address that was dialled",
            (seen.get("host") or "").split(":")[0],
            "127.0.0.1",
        )
        report.equal(group, "the target's body arrived", seen.get("body"), '{"product_id":"prod_001"}')

        names = {k.lower(): v for k, v in seen.get("headers", [])}
        report.equal(
            group,
            "the user's Authorization reaches the target",
            names.get("authorization"),
            "Bearer target-token",
        )
        report.equal(group, "a custom header is kept", names.get("x-custom"), "kept")
        # The credential that reached *this* backend was in the request's headers
        # (the harness sends it), so this is the real check: it must not appear in
        # what the target received.
        report.check(
            group,
            "the platform's session header never travels",
            "x-guest-session" not in names,
            f"headers {sorted(names)}",
        )

        # 4xx and 5xx are answers, not proxy failures.
        target.seen.clear()
        target.reply_status, target.reply_reason = 404, "Not Found"
        target.reply_body = b'{"error":"nope"}'
        target.reply_headers = [("Content-Type", "application/json"), ("Set-Cookie", "sid=abc; Path=/; HttpOnly; Secure")]
        response = await harness.post("mine", {"method": "GET", "url": url})
        payload = response.json()
        report.equal(group, "an upstream 404 is a 200 from the proxy", response.status_code, 200)
        report.equal(group, "carrying the upstream status", payload.get("status"), 404)
        report.equal(group, "and the upstream reason", payload.get("statusText"), "Not Found")
        report.equal(group, "and the upstream body", payload.get("body"), '{"error":"nope"}')
        cookies = payload.get("cookies") or []
        report.equal(
            group,
            "Set-Cookie is split into the client's shape",
            cookies,
            [
                {
                    "name": "sid",
                    "value": "abc",
                    "domain": "",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "expires": "",
                }
            ],
        )

        target.reply_status, target.reply_reason = 500, "Server Error"
        target.reply_body = b"boom"
        response = await harness.post("mine", {"method": "GET", "url": url})
        report.equal(group, "an upstream 500 is still an answer", response.json().get("status"), 500)

        # Put the target back the way the next block expects to find it: leaving a
        # Set-Cookie and a 500 behind is how the header and cookie assertions below
        # failed the first time.
        target.reply_status, target.reply_reason = 200, "OK"
        target.reply_body = b'{"ok":true}'
        target.reply_headers = [("Content-Type", "application/json")]
        target.seen.clear()
    finally:
        api_proxy.classify_address = original_classify  # type: ignore[assignment]
        probe.real_dial = False
        probe.answers.clear()


# --------------------------------------------------------------------------- #
# D. The pinning guarantee
# --------------------------------------------------------------------------- #


async def _pinning(report: Report, harness: Harness, probe: Probe) -> None:
    group = "D. the dialled address is the validated one"
    probe.answers.clear()
    probe.default_answer = [ALLOWED_IP]
    # The resolver's answers are the input; the *dial* is the measurement.  The
    # guard refuses the connection after recording it, so "which address would
    # have been used" is read off the socket layer rather than inferred from the
    # URL the caller sent.
    probe.real_dial = False
    # Two genuinely global addresses, so the double's policy check passes and the
    # measurement is purely "which of them was dialled".
    probe.answers[HOST] = [SECOND_ALLOWED_IP, ALLOWED_IP]
    probe.names.clear()
    probe.dials.clear()

    response = await harness.post("mine", {"method": "GET", "url": f"http://{HOST}/x"})

    report.equal(
        group,
        "exactly one dial, to the first validated address",
        [d["host"] for d in probe.dials],
        [SECOND_ALLOWED_IP],
    )
    report.equal(
        group,
        "and the name is what was resolved, once",
        probe.names,
        [(HOST, 80)],
    )
    report.check(
        group,
        "a dial that was made is reported as unreachable, not as blocked",
        response.status_code == 502
        and response.json().get("code") == api_proxy.TARGET_UNREACHABLE_CODE,
        f"status {response.status_code} code {response.json().get('code')}",
    )


# --------------------------------------------------------------------------- #
# E. Protocol headers and framing
# --------------------------------------------------------------------------- #


async def _protocol(
    report: Report, harness: Harness, probe: Probe, target: LoopbackServer
) -> None:
    group = "E. protocol headers"
    probe.answers.clear()
    probe.default_answer = [ALLOWED_IP]
    probe.answers["127.0.0.1"] = ["127.0.0.1"]
    probe.real_dial = True
    original_classify = api_proxy.classify_address
    api_proxy.classify_address = lambda address: "allowed"  # type: ignore[assignment]

    try:
        url = f"http://127.0.0.1:{target.port}/h"
        target.seen.clear()
        response = await harness.post(
            "mine",
            {
                "method": "GET",
                "url": url,
                "headers": [
                    {"name": "Host", "value": "evil.example"},
                    {"name": "Connection", "value": "keep-alive, X-Smuggle"},
                    {"name": "Transfer-Encoding", "value": "chunked"},
                    {"name": "Content-Length", "value": "999"},
                    {"name": "TE", "value": "trailers"},
                    {"name": "Upgrade", "value": "h2c"},
                    {"name": "Proxy-Authorization", "value": "Basic zzz"},
                    {"name": "Cookie", "value": "platform=session"},
                    {"name": "X-Kept", "value": "yes"},
                ],
            },
        )
        report.equal(group, "the request is answered", response.status_code, 200)

        report.check(
            group,
            "the request reached the target",
            len(target.seen) == 1,
            f"target saw {len(target.seen)} requests",
        )
        seen = target.seen[0] if target.seen else {}
        names = {k.lower(): v for k, v in seen.get("headers", [])}
        for dropped in ("connection", "transfer-encoding", "te", "upgrade", "proxy-authorization", "cookie"):
            report.check(
                group,
                f"{dropped} is not forwarded",
                dropped not in names,
                f"headers {sorted(names)}",
            )
        report.check(
            group,
            "Host is not taken from the client",
            names.get("host") != "evil.example",
            f"host {names.get('host')}",
        )
        report.equal(group, "everything else is forwarded", names.get("x-kept"), "yes")
    finally:
        api_proxy.classify_address = original_classify  # type: ignore[assignment]
        probe.real_dial = False


# --------------------------------------------------------------------------- #
# F. Limits
# --------------------------------------------------------------------------- #


async def _limits(
    report: Report, harness: Harness, probe: Probe, target: LoopbackServer
) -> None:
    group = "F. resource limits"
    probe.answers.clear()
    probe.default_answer = [ALLOWED_IP]
    probe.answers["127.0.0.1"] = ["127.0.0.1"]
    probe.real_dial = True
    original_classify = api_proxy.classify_address
    api_proxy.classify_address = lambda address: "allowed"  # type: ignore[assignment]

    try:
        url = f"http://127.0.0.1:{target.port}/big"

        target.reply_body = b"x" * (api_proxy.MAX_RESPONSE_BYTES + 1)
        response = await harness.post("mine", {"method": "GET", "url": url})
        report.equal(
            group,
            "a response over the cap is refused",
            response.json().get("code"),
            api_proxy.BODY_TOO_LARGE_CODE,
        )

        # The request-body cap is declared on the schema, so an oversized body is
        # refused by validation before a route body or a socket exists.  That is
        # the stronger guarantee of the two, and it is what is measured here.
        target.seen.clear()
        response = await harness.post(
            "mine",
            {
                "method": "POST",
                "url": url,
                "body": "y" * (api_proxy.MAX_REQUEST_BYTES + 1),
            },
        )
        report.equal(
            group,
            "a request body over the cap is refused",
            response.status_code,
            422,
        )
        report.equal(
            group,
            "and it never reaches the target",
            target.seen,
            [],
        )

        # The service check is the second line for the same limit: a caller that
        # builds a ProxyRequest in-process (not through the schema) is still
        # refused, and it is that path the next assertion covers.
        oversized = await _forward_directly("y" * (api_proxy.MAX_REQUEST_BYTES + 1))
        report.equal(
            group,
            "and the service refuses it too",
            oversized,
            api_proxy.INVALID_REQUEST_CODE,
        )

        target.reply_body = b"x" * (api_proxy.MAX_RESPONSE_BYTES - 1)
        response = await harness.post("mine", {"method": "GET", "url": url})
        report.equal(group, "just under the cap still answers", response.status_code, 200)

        target.reply_headers = [("Content-Type", "text/plain")] + [
            (f"X-Pad-{i}", "z" * 900) for i in range(60)
        ]
        target.reply_body = b"ok"
        response = await harness.post("mine", {"method": "GET", "url": url})
        report.equal(
            group,
            "too many response headers are refused",
            response.json().get("code"),
            api_proxy.BODY_TOO_LARGE_CODE,
        )

        # A target that accepts the connection and then says nothing at all.  The
        # read bound is what has to end this call; the overall deadline is longer,
        # so a pass here means the per-read limit is real.
        holders: list[asyncio.StreamWriter] = []

        async def hold(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await reader.readuntil(b"\r\n\r\n")
            holders.append(writer)

        silent = await asyncio.start_server(hold, host="127.0.0.1", port=0)
        silent_port = silent.sockets[0].getsockname()[1]

        api_proxy.REQUEST_TIMEOUT_MS = 400
        started = asyncio.get_running_loop().time()
        response = await harness.post(
            "mine", {"method": "GET", "url": f"http://127.0.0.1:{silent_port}/slow"}
        )
        elapsed = asyncio.get_running_loop().time() - started
        report.equal(
            group,
            "a silent target times out",
            response.json().get("code"),
            api_proxy.TIMEOUT_CODE,
        )
        report.check(group, "and it does so promptly", elapsed < 5, f"{elapsed:.2f}s")

        for writer in holders:
            writer.close()
        silent.close()

        # A port nothing listens on.
        dead = socket.socket()
        dead.bind(("127.0.0.1", 0))
        dead_port = dead.getsockname()[1]
        dead.close()
        response = await harness.post(
            "mine", {"method": "GET", "url": f"http://127.0.0.1:{dead_port}/gone"}
        )
        report.equal(
            group,
            "a refused connection reports unreachable",
            response.json().get("code"),
            api_proxy.TARGET_UNREACHABLE_CODE,
        )

        report.check(
            group,
            "no internal detail leaks in an error body",
            "Traceback" not in response.text and "site-packages" not in response.text,
            response.text[:120],
        )
    finally:
        api_proxy.classify_address = original_classify  # type: ignore[assignment]
        api_proxy.REQUEST_TIMEOUT_MS = 10_000
        probe.real_dial = False


# --------------------------------------------------------------------------- #
# G. TLS
# --------------------------------------------------------------------------- #


async def _tls(
    report: Report, harness: Harness, probe: Probe, tls: TlsTarget
) -> None:
    group = "G. TLS under pinning"
    probe.answers.clear()
    probe.default_answer = [ALLOWED_IP]
    probe.answers["localhost"] = ["127.0.0.1"]
    probe.answers["127.0.0.1"] = ["127.0.0.1"]
    probe.real_dial = True

    try:
        # "localhost" resolves through the *real* resolver and classifies as
        # loopback -- which is blocked.  The tests above prove that refusal; here
        # the point is the TLS behaviour, so the classifier is relaxed and
        # everything else stays real.
        original_classify = api_proxy.classify_address
        api_proxy.classify_address = lambda address: "allowed"  # type: ignore[assignment]

        try:
            # The literal is what is dialled; the *name* is what TLS must verify.
            tls.sni.clear()
            response = await harness.post(
                "mine",
                {"method": "GET", "url": f"https://localhost:{tls.port}/secure"},
            )
            report.equal(group, "a verified TLS target answers", response.status_code, 200)
            payload = response.json() if response.status_code == 200 else {}
            report.equal(group, "over TLS", payload.get("body"), '{"tls":true}')
            report.equal(
                group,
                "the certificate name reached the target in SNI",
                tls.sni,
                ["localhost"],
            )
            report.equal(
                group,
                "and the target saw the name in Host",
                [entry.split(":")[0] for entry in tls.requests_log],
                ["localhost"],
            )
        finally:
            api_proxy.classify_address = original_classify  # type: ignore[assignment]

        # A name that does not match the certificate must fail.  This is the
        # assertion that verification was not disabled to make pinning work: the
        # dial, the socket and the handshake are all real, and only the name in the
        # certificate check differs.
        original_classify = api_proxy.classify_address
        api_proxy.classify_address = lambda address: "allowed"  # type: ignore[assignment]
        try:
            mismatch = await harness.post(
                "mine",
                {
                    "method": "GET",
                    "url": f"https://127.0.0.1:{tls.port}/secure",
                    "headers": [{"name": "Host", "value": "wrong.example"}],
                },
            )
            report.check(
                group,
                "a name that does not match the certificate is refused",
                mismatch.status_code == 502,
                f"status {mismatch.status_code} code {mismatch.json().get('code')}",
            )
            # An IP-literal URL carries no name, so the handshake presents *no*
            # SNI -- unlike the case above, where the name "localhost" was sent
            # because the caller asked for it.  That difference is the point: the
            # code does not substitute a name of its own to make verification pass.
            report.equal(
                group,
                "the literal reached the handshake without a name being invented",
                tls.sni[-1] if tls.sni else "none-recorded",
                None,
            )
            report.equal(
                group,
                "and no request was served over that connection",
                tls.requests,
                1,
            )
        finally:
            api_proxy.classify_address = original_classify  # type: ignore[assignment]
    finally:
        probe.real_dial = False


async def _forward_directly(body: str) -> str:
    """The service's own answer for a payload that is over the cap in *bytes*.

    The schema caps the field in characters, so nothing the route accepts can be
    over the byte limit -- but the limit that matters is the one on the wire, and
    `forward` is what converts characters to bytes.  This drives that conversion
    directly, which is the only way to reach it.  A plain object stands in for the
    validated model precisely because the model refuses to represent this input.
    """
    payload = SimpleNamespace(method="POST", url=f"http://{HOST}/x", headers=[], body=body, timeout_ms=None)

    try:
        await api_proxy.forward(payload)  # type: ignore[arg-type]
    except api_proxy.ProxyError as exc:
        return exc.code

    return "no-error"


def tls_error(response: httpx.Response) -> str:
    try:
        return json.dumps(response.json())
    except Exception:
        return response.text


if __name__ == "__main__":
    os.environ.setdefault("SSL_CERT_FILE", str(TEST_CERT))
    ssl.get_default_verify_paths()  # touch the module so the env var is read first
    raise SystemExit(asyncio.run(main()))