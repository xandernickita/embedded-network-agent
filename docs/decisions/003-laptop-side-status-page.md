# 003 — The status web page runs on the laptop, not the Pi

**Status:** accepted, 2026-11-10

## Decision

`nda web` starts a small HTTP server on the laptop (Python standard library). The browser
polls `/api/status` on it; it forwards `get_status` to the Pi over the existing TCP
protocol and returns the result. The Pi-side server gains no HTTP code.

```
browser ──HTTP──▶ nda web (laptop) ──framed JSON over TCP :5000──▶ nda-server (Pi)
```

## Why

- **Benchmarks stay valid.** The C++ server is the thing being measured. Adding an HTTP
  stack to it would change the binary under test and its event loop.
- **The page demonstrates the protocol** instead of bypassing it: it is one more client of
  `docs/PROTOCOL.md`, like the CLI.
- **No new attack surface on the Pi.** The page binds to `127.0.0.1` by default, so it is
  only reachable from the laptop itself.
- **Scope.** The project plan rules out a web dashboard. This is a single read-only status
  view for demos, not a dashboard; it adds no commands and no history.

## Consequences

- The page only works while `nda web` runs on a machine that can reach the Pi.
- The page holds one TCP connection to the agent and serialises browser requests through a
  lock (`AgentClient` is not thread-safe). Several browser tabs share it.
- The page's "Round trip" is the laptop↔Pi time for `get_status`, measured by the laptop-side
  server; it does not include the browser↔laptop hop.
