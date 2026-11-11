# Embedded Network Diagnostics Agent

A Linux service on a Raspberry Pi 3B that answers telemetry and network-diagnostic
requests from a laptop over a custom TCP protocol, plus a UDP endpoint for measuring loss,
reordering and round-trip time. The server is C++17 on raw POSIX sockets; the laptop
client and benchmarks are Python.

```
$ nda status
Connected to:    nda-pi (nda-pi.local:5000)
Protocol:        TCP
Uptime:          14h 32m
CPU temperature: 48.2 C
Memory usage:    31.4%
Status:          OK
```

| Doc | What's in it |
|---|---|
| [docs/results.md](docs/results.md) | **Measured results**: acceptance tests, latency, throughput, discussion, deviations |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | The wire contract: framing, messages, error codes, UDP datagram format |
| [docs/architecture.md](docs/architecture.md) | Components, event loop, robustness rules, measurement notes |
| [docs/pi-bringup.md](docs/pi-bringup.md) | Flashing, first boot, deploy, troubleshooting |
| [docs/remote-access.md](docs/remote-access.md) | Tailscale: reaching the Pi from any network, and benchmarking the tunnel |
| [docs/decisions/](docs/decisions/) | Why C++ + Python, why length-prefixed frames, why the status page lives on the laptop |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branches, PRs, commit style |

## Layout

```
server/            C++ agent (CMake)
  src/             framing, protocol dispatcher, telemetry, poll loop, main
  tests/           unit tests + fake /proc and /sys trees
client/            Python package `nda_client` and the `nda` CLI
  tests/           unit tests + loopback integration tests against the real server
deploy/            Pi setup, install, systemd unit, netem impairment, Tailscale
benchmarks/results CSV results and charts (committed)
docs/              protocol, architecture, bring-up, decisions
```

## Quick start

### Laptop (Windows, PowerShell)

```powershell
py -m venv .venv; .venv\Scripts\Activate.ps1
pip install -e "client[dev,plot]"
$env:NDA_HOST = "nda-pi.local"
nda status
```

### Server on Linux / WSL2 (for development without the Pi)

```bash
cmake -S server -B server/build && cmake --build server/build -j
ctest --test-dir server/build --output-on-failure
./server/build/nda-server --bind 127.0.0.1        # then: NDA_HOST=127.0.0.1 nda status
pytest client                                    # runs integration tests against the build
```

### Pi

See [docs/pi-bringup.md](docs/pi-bringup.md). Short version, on the Pi:

```bash
git clone https://github.com/xandernickita/embedded-network-agent.git
cd embedded-network-agent && ./deploy/pi-setup.sh
```

## Status page

```powershell
nda web                     # then open http://localhost:8080/
```

A live view of `nda status` that refreshes every 2 s and shows when the Pi is unreachable.
It runs on the laptop and talks to the Pi over the normal TCP protocol, so nothing is added
to the Pi ([decision 003](docs/decisions/003-laptop-side-status-page.md)). Options:
`--web-port`, `--refresh`, `--listen` (default `127.0.0.1`: this laptop only).

## Benchmarks

```bash
nda bench matrix --link ethernet --out benchmarks/results/ethernet.csv
nda bench matrix --link wifi     --out benchmarks/results/wifi.csv
nda bench udp --payload 256 --requests 10000 --link wifi --out benchmarks/results/udp-loss.csv
nda bench matrix --host nda-pi --link tailscale --out benchmarks/results/tailscale.csv   # via the tunnel
nda plot benchmarks/results/ethernet.csv benchmarks/results/wifi.csv benchmarks/results/tailscale.csv
```

Run each matrix **three times** into the same CSV. Single runs over Wi-Fi vary by 20-40 %
and occasional ~120 ms stalls land on random configurations, so the charts plot the
median across runs with the min-max range as error bars.

Each row records the run id, link type, client platform and the server's hostname and
kernel, as the plan requires. Impair the Pi's link to validate loss detection:

```bash
./deploy/netem.sh eth0 loss 5%    # on the Pi; measured loss should be close to 5 %
./deploy/netem.sh eth0 clear
```

## Acceptance tests (plan section 5)

All passed on the Pi on 11 Nov 2026. Measured numbers, discussion and deviations from
the plan are in [docs/results.md](docs/results.md).

| Test | How it was run | Result |
|---|---|---|
| TCP reliability | `nda bench echo --requests 10000` (Pi); `test_tcp_reliability_sequential_requests` (CI) | 10,000 / 10,000 |
| TCP correctness | `test_malformed_input_*`, `test_oversize_frame_*`, `test_partial_frame_*`, C++ `protocol:` tests (CI) | Documented errors; server stays up |
| UDP delivery | `nda bench udp --requests 10000`; with `netem.sh eth0 loss 5%` | 0 % lost; 4.96 % measured vs 5 % injected |
| Latency p50/p95/p99 | `nda bench matrix` (latency row), 3 runs per path | Ethernet 2.56 / 4.06 / 5.74 ms |
| Throughput | `nda bench matrix`, 4 payloads × 1/2/5 clients | Up to 1,590 req/s (64 B, 5 clients) |
| Concurrency (5 clients) | `matrix`; `test_five_concurrent_clients_without_corruption` (CI) | 180,000 requests, 0 corrupted |
| Recovery | `sudo systemctl restart nda-server` during `nda ping -n 3000` | Client exits cleanly with a connection error |
| Stability | `nda bench echo --requests 1000000` + `VmRSS` sampled every minute | 35.4 min, 0 errors, RSS flat at 3.4 MB |
