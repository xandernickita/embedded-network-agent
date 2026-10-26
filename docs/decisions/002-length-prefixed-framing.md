# 002 — Length-prefixed frames instead of newline-delimited JSON

**Status:** accepted, 2026-10-26

## Decision

Each TCP message is a 4-byte big-endian length followed by that many bytes of UTF-8 JSON,
capped at 64 KiB. The project plan's first suggestion was newline-delimited JSON.

## Why

- The receiver knows how many bytes to wait for, and can reject an oversized message from
  the header alone, before buffering any of it. With newlines it has to keep buffering
  until it sees `\n`, so the size limit is enforced late.
- Payloads can contain any byte, including newlines, without escaping rules to get wrong.
- Handling a header and a body that each arrive split across several `recv()` calls is the
  core problem of stream protocols; this format makes it explicit and testable.

## Consequences

- Frames can't be typed by hand with `nc`. The `nda` CLI and the integration tests build
  them instead.
- A bad header means the stream position is lost, so the server answers once
  (`BAD_FRAME` / `FRAME_TOO_LARGE`) and closes the connection.
