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

## Installation

First-time setup takes about an hour, most of it waiting for the SD card and `apt`.
At the end, `nda status` on your laptop shows live telemetry from the Pi.

### What you need

| Item | Requirement |
|---|---|
| Device | Raspberry Pi 3B or 3B+ (tested on a 3B+), microSD card ≥ 16 GB, 5 V / 2.5 A supply |
| Laptop | Windows, macOS or Linux with Python ≥ 3.11 and Git |
| Network | Both machines on the same network: a home router, Ethernet, or a phone hotspot on 2.4 GHz. Many campus networks block device-to-device traffic. |

### 1. Laptop: install the client

Create an SSH key if you don't have one (`ssh-keygen -t ed25519`, Enter at every prompt), then:

```bash
git clone https://github.com/xandernickita/embedded-network-agent.git
cd embedded-network-agent
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell
# source .venv/bin/activate         # macOS / Linux
pip install -e "client[dev,plot]"
pytest client                       # unit tests pass; integration tests skip without a local server
```

The client uses only the Python standard library; `[plot]` adds matplotlib for charts.

### 2. Flash the SD card

In [Raspberry Pi Imager](https://www.raspberrypi.com/software/): device **Raspberry Pi 3**,
OS **Raspberry Pi OS Lite (64-bit)** (under "Raspberry Pi OS (other)"), then edit the settings:

| Setting | Value |
|---|---|
| Hostname | `nda-pi` |
| Username / password | your choice; the username is what you SSH in with |
| Wireless LAN | SSID, password, country (skip for Ethernet only) |
| Services | SSH enabled, **public-key authentication only**, paste your `id_ed25519.pub` |

If Windows offers to format the card afterwards, click **Cancel**: the Linux partition is unreadable to Windows, not broken.

### 3. Pi: first boot and install

Connect Ethernet if you use it, then power. After about two minutes:

```bash
ssh <username>@nda-pi.local          # from the laptop
```

On the Pi:

```bash
sudo apt-get update && sudo apt-get full-upgrade -y && sudo reboot
# reconnect, then:
sudo apt-get install -y git
git clone https://github.com/xandernickita/embedded-network-agent.git
cd embedded-network-agent
./deploy/pi-setup.sh
```

`pi-setup.sh` installs the toolchain, builds the server with warnings as errors, runs the
unit tests and installs `nda-server` as a systemd service that starts at boot. It takes
10–15 minutes on a Pi 3 and ends with `100% tests passed`, `active (running)` and the
device details (record those in [docs/pi-environment.md](docs/pi-environment.md)).

Then check the power supply: `vcgencmd get_throttled` must print `throttled=0x0`.
Anything else means undervoltage, which causes network drops and invalid benchmarks.

### 4. First contact

From the laptop, with the virtual environment active:

```bash
nda --host nda-pi.local status
nda --host nda-pi.local ping -n 20
nda --host nda-pi.local diag default_route
nda --host nda-pi.local web           # live status page; open the address it prints
```

Set `NDA_HOST=nda-pi.local` (PowerShell: `$env:NDA_HOST = "nda-pi.local"`) to drop `--host`.

### 5. Optional: reach the Pi from any network

Install [Tailscale](https://tailscale.com/download) on the laptop and sign in. On the Pi:

```bash
./deploy/tailscale.sh                 # approve the login link it prints
```

Disable key expiry for `nda-pi` in the Tailscale admin console. `nda --host nda-pi status`
then works from anywhere. Benchmark rules for the tunnel: [docs/remote-access.md](docs/remote-access.md).

### Updating

```bash
git pull && ./deploy/install.sh                  # Pi: rebuild, test, restart the service
git pull && pip install -e "client[dev,plot]"    # laptop
```

### Troubleshooting

| Symptom | Fix |
|---|---|
| `Permission denied (publickey)` | Use the username set in Imager; check the key you pasted is this laptop's `id_ed25519.pub` |
| `nda-pi.local` doesn't resolve | Machines are on different networks, or mDNS is blocked: use the Pi's IP from the router |
| `connection error` / `no agent answering` | On the Pi: `systemctl status nda-server`, `journalctl -u nda-server -n 20 -o cat` |
| Pi never joins Wi-Fi | Wrong password or Wi-Fi country not set in Imager: re-flash |
| `nda web` can't use port 8080 | Windows reserves it on some machines; `nda web` falls back to a free port and prints it |
| `git clone` asks for a password on the Pi | The repository is private: `sudo apt-get install -y gh && gh auth login`, then clone again |

Step-by-step bring-up with more detail: [docs/pi-bringup.md](docs/pi-bringup.md).

### Developing without a Pi

The server builds and runs on any Linux (or WSL2), so the whole stack can be tested on one machine:

```bash
cmake -S server -B server/build -DNDA_WERROR=ON && cmake --build server/build -j
ctest --test-dir server/build --output-on-failure
./server/build/nda-server --bind 127.0.0.1       # then: nda --host 127.0.0.1 status
pytest client                                   # also runs the loopback integration tests
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
