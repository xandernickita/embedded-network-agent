"""Loopback integration fixture: starts the real C++ nda-server on free ports.

Looks for the binary in $NDA_SERVER_BIN, then server/build/nda-server. Integration tests
are skipped (not failed) when it isn't built, so `pytest` still runs the unit tests on a
Windows laptop with no compiler.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def server_binary() -> Path | None:
    candidates = [os.environ.get("NDA_SERVER_BIN"), REPO / "server" / "build" / "nda-server"]
    for c in candidates:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return Path(c)
    return None


@dataclass
class RunningServer:
    binary: Path
    args: list[str]
    host: str = "127.0.0.1"
    tcp_port: int = 0
    udp_port: int = 0
    proc: subprocess.Popen | None = None
    logs: list[dict] = field(default_factory=list)

    def start(self) -> RunningServer:
        ports = ["--tcp-port", str(self.tcp_port), "--udp-port", str(self.udp_port)]
        self.proc = subprocess.Popen(
            [str(self.binary), "--bind", self.host, *ports, *self.args],
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            text=True,
        )
        ready: queue.Queue = queue.Queue()

        def pump(stream):
            for line in stream:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.logs.append(ev)
                if ev.get("event") in ("listening", "bind_failed"):
                    ready.put(ev)

        threading.Thread(target=pump, args=(self.proc.stderr,), daemon=True).start()
        ev = ready.get(timeout=10)
        if ev["event"] != "listening":
            raise RuntimeError(f"server failed to start: {ev}")
        # Keep the same ports across restarts so the recovery test reconnects to the same address.
        self.tcp_port, self.udp_port = ev["tcp_port"], ev["udp_port"]
        return self

    def stop(self) -> int | None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        return self.proc.returncode if self.proc else None

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


@pytest.fixture
def server():
    binary = server_binary()
    if binary is None:
        pytest.skip("nda-server not built (cmake -S server -B server/build && cmake --build server/build)")
    fixtures = REPO / "server" / "tests" / "fixtures" / "pi3b"
    s = RunningServer(
        binary,
        ["--max-clients", "8", "--idle-timeout", "3",
         "--proc-root", str(fixtures / "proc"), "--sys-root", str(fixtures / "sys")],
    ).start()  # fmt: skip
    yield s
    s.stop()
