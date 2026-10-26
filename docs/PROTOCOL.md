# Wire protocol (v1)

This file is the contract between `server/` (C++) and `client/` (Python).
If a message shape changes, change this file in the **same pull request** as the code
(CONTRIBUTING rule 4).

Defaults: TCP port **5000** (commands), UDP port **5001** (benchmark echo).

---

## 1. TCP: framed JSON request/response

TCP is a byte stream, so the application has to say where each message ends.

### Framing

```
+----------------------------+---------------------------------+
| length : uint32 big-endian | payload : `length` bytes (UTF-8 JSON) |
+----------------------------+---------------------------------+
```

- `length` counts payload bytes only (not the 4-byte header).
- `1 <= length <= 65536`. A header of `0` or `> 65536` is a framing error: the server
  sends one `FRAME_TOO_LARGE` / `BAD_FRAME` error response (with `request_id: null`)
  and closes the connection, because it can no longer find the next frame boundary.
- A peer may deliver a frame across any number of `recv()` calls; both sides must
  buffer until the full frame has arrived.
- One connection carries many requests. Responses come back in request order.

### Request

```json
{ "version": 1, "request_id": 42, "command": "get_status", "args": {} }
```

| Field | Type | Rules |
|---|---|---|
| `version` | int | Must be `1`. Otherwise `UNSUPPORTED_VERSION`. |
| `request_id` | int, 0 … 2^53−1 | Chosen by the client; echoed back unchanged. |
| `command` | string | One of the commands below. Otherwise `UNKNOWN_COMMAND`. |
| `args` | object | Optional; defaults to `{}`. |

### Response

```json
{ "version": 1, "request_id": 42, "status": "ok", "data": { ... } }
```

```json
{ "version": 1, "request_id": 42, "status": "error",
  "error": { "code": "UNKNOWN_COMMAND", "message": "no command 'reboot'" } }
```

`request_id` is `null` only when the request was too broken to read one.

### Error codes

| Code | Meaning | Connection after |
|---|---|---|
| `BAD_FRAME` | Length header is 0. | Closed |
| `FRAME_TOO_LARGE` | Length header > 65536. | Closed |
| `MALFORMED_JSON` | Payload is not valid JSON or not an object. | Open |
| `INVALID_REQUEST` | A required field is missing or has the wrong type. | Open |
| `UNSUPPORTED_VERSION` | `version` is not 1. | Open |
| `UNKNOWN_COMMAND` | `command` is not in the table below. | Open |
| `INVALID_ARGS` | `args` fail validation for that command. | Open |
| `SERVER_BUSY` | Max clients reached; sent once, then closed. | Closed |
| `INTERNAL_ERROR` | Handler failed; details in the server log. | Open |

The server **never** exits on bad input.

### Commands

| Command | `args` | `data` |
|---|---|---|
| `ping` | — | `{ "server_time_ns": int }` (server monotonic clock; do **not** compare with client clocks) |
| `echo` | `{ "payload": string }` (≤ 60000 bytes) | `{ "payload": string }` unchanged — used for throughput tests |
| `get_status` | — | see below |
| `get_netinfo` | — | `{ "interfaces": [ { "name", "operstate", "mtu", "mac", "ipv4": [str], "rx_bytes", "tx_bytes", "rx_errors", "tx_errors", "rx_dropped", "tx_dropped" } ] }` |
| `get_metrics` | — | `{ "server_uptime_s", "requests_total", "errors_total", "clients_active", "clients_total", "bytes_rx", "bytes_tx", "udp_datagrams_rx", "udp_datagrams_tx", "udp_datagrams_invalid" }` |
| `run_diagnostic` | `{ "test": string }` | see below |

`get_status` data:

```json
{
  "hostname": "nda-pi",
  "uptime_seconds": 52320.4,
  "cpu_temperature_c": 48.2,
  "load_avg": [0.12, 0.08, 0.05],
  "memory_percent": 31.4,
  "memory_total_kb": 948304,
  "memory_available_kb": 650512,
  "kernel": "6.12.25+rpt-rpi-v8"
}
```

Any value the platform cannot provide (for example no thermal zone on a laptop or
CI runner) is `null`, never an error.

### `run_diagnostic` tests

Only these names are accepted (`INVALID_ARGS` otherwise). None of them run a shell
or an external program.

| `test` | What it does | `data` |
|---|---|---|
| `default_route` | Reads `/proc/net/route`. | `{ "interface", "gateway" }` or both `null` |
| `link_stats` | Reads error/drop counters from `/sys/class/net/*/statistics`. | `{ "interfaces": { "<name>": { counters } } }` |
| `gateway_tcp` | Times a TCP `connect()` to the default gateway on port 53, 80 then 443 (500 ms timeout each; blocks the event loop, see architecture.md). | `{ "gateway", "port", "connect_ms" }` or `{ "gateway", "reachable": false }` |

---

## 2. UDP: benchmark echo

The UDP endpoint exists to measure delivery, ordering and round-trip time. It is a
separate port so a broken benchmark can't disturb the command channel.

### Datagram

All integers big-endian.

```
offset  size  field
0       4     magic = "NDA1" (0x4E 0x44 0x41 0x31)
4       4     seq        uint32, client-assigned, starts at 0
8       8     t_send_ns  uint64, client monotonic clock
16      n     padding    any bytes; total datagram 16 … 1472 bytes
```

The server sends the datagram **back unchanged** to the sender's address and port.
Datagrams shorter than 16 bytes, longer than 1472, or without the magic are dropped
and counted in `udp_datagrams_invalid`.

1472 = 1500-byte Ethernet MTU − 20 (IPv4) − 8 (UDP), so no test datagram is
fragmented.

### What the client computes

- **RTT** = client receive time − `t_send_ns` (one clock, so no clock sync needed).
- **Loss** = sent − unique sequence numbers received before the timeout.
- **Duplicates** = sequence numbers received more than once.
- **Reordered** = datagrams whose `seq` is lower than the highest `seq` already seen.

One-way latency is **not** reported: the Pi and laptop clocks are not synchronized.
