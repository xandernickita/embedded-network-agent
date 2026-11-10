# Architecture

```
 LAPTOP (Windows, Python 3.11+)                         RASPBERRY PI 3B (Pi OS Lite 64-bit)
 ┌──────────────────────────────┐                       ┌───────────────────────────────────────────┐
 │ nda CLI         (cli.py)     │                       │ nda-server  (C++17, one process, systemd) │
 │  status / ping / diag        │   TCP :5000           │  ┌─────────────── poll() loop ───────────┐ │
 │ AgentClient    (client.py)   │ ◀═══ framed JSON ════▶│  │ listen fd · client fds · udp fd       │ │
 │  request ids, timeouts,      │                       │  └───────┬──────────────────────┬────────┘ │
 │  reconnect + retry           │                       │   FrameDecoder            UDP echo         │
 │ framing.py                   │                       │   (framing.cpp)           (udp_echo.hpp)   │
 │                              │   UDP :5001           │          │                                 │
 │ udp.py  seq + t_send, RTT,   │ ◀════ NDA1 datagrams ▶│   Dispatcher (protocol.cpp)                │
 │         loss, dup, reorder   │                       │    validate → run command → respond        │
 │ bench.py → results.csv       │                       │          │                                 │
 │ plot.py  → 2 charts          │                       │   Telemetry (telemetry.cpp)                │
 └──────────────────────────────┘                       │    /proc · /sys · getifaddrs               │
                                                        │   Metrics · JSON-line logs → journald      │
                                                        └───────────────────────────────────────────┘
```

## Layers

| Layer | Code | Responsibility |
|---|---|---|
| Transport | `server.cpp`, kernel TCP/UDP | Sockets, non-blocking I/O, accept, backpressure, timeouts |
| Framing | `framing.cpp` / `framing.py` | Turn the TCP byte stream into discrete messages |
| Application protocol | `protocol.cpp` / `client.py` | Versioned JSON request/response, validation, error codes |
| Services | `telemetry.cpp` | Read-only system and network information |

`protocol.cpp` and `framing.cpp` have no socket code, so every error path is unit-tested
without a network (`server/tests`). The socket layer is covered by the Python loopback
integration tests (`client/tests/test_integration.py`), which start the real binary.

## Concurrency model

One thread, one `poll()` loop over the listening socket, the UDP socket and every client.
All sockets are non-blocking. Each client has its own `FrameDecoder` (input buffer) and
output buffer; partial reads and partial writes are normal and are simply continued on the
next loop iteration.

Why not a thread per client: the work per request is microseconds of `/proc` reads and
JSON, so the server is I/O-bound. One thread means no locks around the metrics counters
and no data races to explain in the report. The Pi 3B has four cores, so the benchmark
"throughput vs clients" chart is where this choice shows up; discuss it honestly.

Robustness rules:

- **Backpressure:** a client with > 1 MiB of unsent replies stops being read until it
  drains, so a client that sends but never reads can't make the server buffer forever.
- **Idle timeout:** connections with no traffic for 60 s are closed.
- **Max clients:** the 33rd connection gets one `SERVER_BUSY` frame and is closed.
- **Framing errors** close the connection after one error reply (the stream position is lost).
- **Malformed JSON / bad requests** get an error reply and the connection stays open.
- `SIGTERM`/`SIGINT` stop the loop cleanly; `SIGPIPE` is ignored and `send()` uses
  `MSG_NOSIGNAL`, so a vanished client can't kill the process.

Known limitation: `run_diagnostic gateway_tcp` performs blocking `connect()` attempts
(up to 3 × 500 ms) inside the loop, so other clients wait while it runs. Acceptable for an
operator-triggered diagnostic; it would move to a worker thread if it mattered.

## Why TCP and UDP are on separate ports

The command channel needs reliability and ordering (TCP). The benchmark channel must be
able to observe loss and reordering, which TCP would hide by retransmitting (UDP). Putting
them on separate sockets also means a flood of benchmark datagrams can't delay a command.

## Measurement notes

- RTT is always measured on one clock (the client's), so the Pi and laptop clocks never
  need to agree. One-way latency is not reported.
- The client uses `time.perf_counter_ns()`: on Windows `time.monotonic()` ticks every
  ~15.6 ms, which is larger than a LAN round trip.
- UDP `msgs_per_s` is the **offered load** set by `--interval`, not the server's capacity.
  `time.sleep()` granularity makes the real interval longer than requested; the CSV
  records the measured rate, not the requested one.
- TCP `payload_bytes_per_s` counts application payload in one direction. Framing and the
  JSON envelope add ~70 bytes per message, which dominates at 64-byte payloads.
- UDP sizes stop at 1472 bytes (1500 MTU − 20 IP − 8 UDP). Larger datagrams fragment at the
  IP layer, which would measure the kernel's reassembly, not this protocol. Over Tailscale the
  limit is 1252 (1280 MTU); `nda bench` applies it automatically for `--link tailscale`.
- UDP `send_errors` (the OS refused the datagram) are reported separately from `lost`
  (sent but never echoed), so a local error is never mistaken for network loss.
