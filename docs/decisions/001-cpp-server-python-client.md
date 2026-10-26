# 001 — C++ server, Python client

**Status:** accepted, 2026-10-26

## Decision

The Pi-side server is C++17 with raw POSIX sockets and a `poll()` loop. The laptop client,
benchmarks and charts are Python (standard library only, matplotlib optional).

## Why

- The server is the "embedded" part: memory use, non-blocking I/O, partial reads/writes and
  framing are the skills the project is meant to show, and Python's `socket` module hides
  some of them behind conveniences like `sendall`.
- The client is tooling. Python is faster to change, runs natively on the Windows laptop,
  and makes CSV and charts trivial.
- The project plan offers this split as its systems-programming option.

## Consequences

- Two implementations of the framing (`framing.cpp`, `framing.py`) must agree. The
  contract lives in `docs/PROTOCOL.md`; the integration tests exercise both together.
- The server can't be run natively on Windows. Develop it in WSL2 or directly on the Pi;
  CI builds and tests it on Linux for every pull request.
