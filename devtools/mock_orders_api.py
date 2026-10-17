"""A local Orders API for manual ApiPilot testing.

Independent of the ApiPilot backend: it listens on its own loopback port, knows
nothing about the product, and exists so a test plan has a real service to call.

    python devtools/mock_orders_api.py
    Invoke-RestMethod http://127.0.0.1:18002/health

Environment overrides: MOCK_ORDERS_HOST, MOCK_ORDERS_PORT.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_HOST = os.environ.get("MOCK_ORDERS_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("MOCK_ORDERS_PORT", "18002"))

# Created orders, kept in memory for the life of the process.
_ORDERS: dict[str, dict[str, object]] = {}
_LOCK = threading.Lock()

# When set, a created order is echoed with an orderId alias as well as id.
# This is a compatibility shim, not part of the documented contract: the current
# run executor locates the field to extract by the *variable name* it was told to
# produce (run_executor.py: find_value(response.json, step.produces)), so a plan
# that extracts into orderId can only succeed if the response carries that name.
# Off by default so the service still answers exactly what the OpenAPI document
# declares.
_ALIAS_ORDER_ID = False


def _log(method: str, path: str, status: int, note: str = "") -> None:
    suffix = " " + note if note else ""
    print(f"{method} {path} -> {status}{suffix}", flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        return

    def _send(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]

        if path == "/health":
            _log("GET", path, 200)
            self._send(200, {"status": "ok"})
            return

        if path.startswith("/orders/"):
            order_id = path[len("/orders/"):]
            with _LOCK:
                order = _ORDERS.get(order_id)
            if order is None:
                _log("GET", path, 404, "(no such order)")
                self._send(404, {"error": "order-not-found", "id": order_id})
                return
            _log("GET", path, 200)
            self._send(200, dict(order))
            return

        _log("GET", path, 404, "(unknown path)")
        self._send(404, {"error": "unknown-path", "path": path})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]

        if path != "/orders":
            _log("POST", path, 404, "(unknown path)")
            self._send(404, {"error": "unknown-path", "path": path})
            return

        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""

        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            _log("POST", path, 400, "(body is not JSON)")
            self._send(400, {"error": "invalid-json"})
            return

        if not isinstance(payload, dict):
            _log("POST", path, 400, "(body is not an object)")
            self._send(400, {"error": "invalid-body"})
            return

        product_id = payload.get("productId")
        quantity = payload.get("quantity")

        if not isinstance(product_id, str) or product_id == "":
            _log("POST", path, 400, "(productId must be a non-empty string)")
            self._send(400, {"error": "invalid-productId"})
            return

        if not isinstance(quantity, int) or isinstance(quantity, bool):
            _log("POST", path, 400, "(quantity must be an integer)")
            self._send(400, {"error": "invalid-quantity"})
            return

        order_id = "order_" + uuid.uuid4().hex[:12]
        order: dict[str, object] = {"id": order_id, "status": "created"}
        if _ALIAS_ORDER_ID:
            order["orderId"] = order_id

        with _LOCK:
            _ORDERS[order_id] = order

        _log("POST", path, 201, "(created %s)" % order_id)
        self._send(201, dict(order))


def main() -> int:
    global _ALIAS_ORDER_ID

    parser = argparse.ArgumentParser(description="Local Orders API for ApiPilot manual testing.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--alias-order-id",
        action="store_true",
        help="also echo the created id as orderId (shim for extract-by-variable-name)",
    )
    args = parser.parse_args()

    _ALIAS_ORDER_ID = args.alias_order_id

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True

    print(f"Orders API listening on http://{args.host}:{args.port}", flush=True)
    print("  GET  /health", flush=True)
    print("  POST /orders", flush=True)
    print("  GET  /orders/{orderId}", flush=True)
    if _ALIAS_ORDER_ID:
        print("  (alias shim on: created orders also carry orderId)", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping.", flush=True)
    finally:
        server.shutdown()
        server.server_close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
