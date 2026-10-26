"""TCP request/response client."""

from __future__ import annotations

import itertools
import json
import os
import socket
import time
from typing import Any

from . import framing

PROTOCOL_VERSION = 1
DEFAULT_TCP_PORT = 5000
DEFAULT_UDP_PORT = 5001


def default_host() -> str:
    return os.environ.get("NDA_HOST", "127.0.0.1")


class AgentError(Exception):
    """The server answered with status "error" (a documented error code)."""

    def __init__(self, code: str, message: str, request_id: int | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.request_id = request_id


class AgentConnectionError(Exception):
    """No usable connection: refused, reset, timed out, or the server went away mid-request."""


class AgentClient:
    """One TCP connection to the agent. Not thread-safe: use one client per thread."""

    def __init__(self, host: str | None = None, port: int = DEFAULT_TCP_PORT, timeout: float = 5.0):
        self.host = host or default_host()
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._ids = itertools.count(1)

    # -- connection -------------------------------------------------------------------
    def connect(self) -> AgentClient:
        self.close()
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise AgentConnectionError(f"cannot connect to {self.host}:{self.port}: {e}") from e
        sock.settimeout(self.timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        return self

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def __enter__(self) -> AgentClient:
        return self.connect()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- requests ---------------------------------------------------------------------
    def send_raw(self, payload: bytes) -> dict[str, Any]:
        """Send one framed payload as-is and return the decoded response (for tests)."""
        if self._sock is None:
            self.connect()
        assert self._sock is not None
        try:
            self._sock.sendall(framing.encode(payload))
            return json.loads(framing.recv_frame(self._sock))
        except (OSError, ConnectionError, framing.FramingError) as e:
            self.close()
            raise AgentConnectionError(f"request to {self.host}:{self.port} failed: {e}") from e

    def request(self, command: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a command and return its `data`. Raises AgentError or AgentConnectionError."""
        rid = next(self._ids)
        msg = {"version": PROTOCOL_VERSION, "request_id": rid, "command": command, "args": args or {}}
        resp = self.send_raw(json.dumps(msg, separators=(",", ":")).encode())
        if resp.get("request_id") not in (rid, None):
            self.close()
            raise AgentConnectionError(f"response id {resp.get('request_id')} does not match request {rid}")
        if resp.get("status") != "ok":
            err = resp.get("error") or {}
            raise AgentError(err.get("code", "UNKNOWN"), err.get("message", ""), resp.get("request_id"))
        return resp["data"]

    def request_with_retry(
        self, command: str, args: dict[str, Any] | None = None, retries: int = 3, backoff: float = 0.5
    ) -> dict[str, Any]:
        """Reconnect and retry on connection failures only (server restart, Wi-Fi blip).

        Safe because every command is read-only: running one twice changes nothing.
        """
        for attempt in range(retries + 1):
            try:
                return self.request(command, args)
            except AgentConnectionError:
                if attempt == retries:
                    raise
                time.sleep(backoff * (2**attempt))
                try:
                    self.connect()
                except AgentConnectionError:
                    continue
        raise AssertionError("unreachable")

    # -- convenience ------------------------------------------------------------------
    def ping(self) -> float:
        """Round-trip time of one ping, in milliseconds."""
        t0 = time.perf_counter_ns()
        self.request("ping")
        return (time.perf_counter_ns() - t0) / 1e6
