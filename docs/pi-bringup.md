# Pi bring-up checklist (Raspberry Pi 3B)

Goal for the first session: **laptop runs `nda status` against the Pi.** Expect about
an hour, most of it waiting on the SD card write and `apt`.

## Before you have the Pi (do now)

- [ ] Install **Raspberry Pi Imager** on the laptop.
- [ ] Have a microSD card (16 GB+) and a reader.
- [ ] Know your Wi-Fi SSID and password, **or** have an Ethernet cable and a free router/switch port.
      Ethernet is strongly preferred for benchmark numbers (see "Wi-Fi vs Ethernet" below).
- [ ] Make sure the laptop has an SSH key: `ssh-keygen -t ed25519` in PowerShell if
      `~\.ssh\id_ed25519.pub` doesn't exist.
- [ ] Clone this repo on the laptop and install the client:
      ```powershell
      git clone https://github.com/xandernickita/embedded-network-agent.git
      cd embedded-network-agent
      py -m venv .venv; .venv\Scripts\Activate.ps1
      pip install -e "client[dev,plot]"
      pytest client            # unit tests pass; integration tests skip (no server on Windows)
      ```
- [ ] **Campus network check.** If you plan to test on LTU Wi-Fi, check whether it blocks
      device-to-device traffic (client isolation). Many campus networks do. If it does,
      use a home router, a phone hotspot, or a direct Ethernet cable.

## Flash the card

In Raspberry Pi Imager:

| Setting | Value |
|---|---|
| Device | Raspberry Pi 3 |
| OS | Raspberry Pi OS **Lite (64-bit)** — under "Raspberry Pi OS (other)" |
| Hostname | `nda-pi` |
| Username | your choice (examples below use `alex`) |
| Wi-Fi | SSID / password / country `US` (skip if using Ethernet only) |
| Locale | America/Detroit |
| Services | Enable SSH, **public-key only**, paste the contents of `id_ed25519.pub` |

64-bit Lite: the 3B's Cortex-A53 is 64-bit, and Lite has no desktop eating the 1 GB of RAM.

## First boot

```powershell
ssh alex@nda-pi.local          # wait ~90 s after power-on for first-boot resize
```

If `nda-pi.local` doesn't resolve, find the Pi's IP in the router's client list and use that.

On the Pi:

```bash
sudo apt-get update && sudo apt-get full-upgrade -y && sudo reboot
# reconnect, then:
git clone https://github.com/xandernickita/embedded-network-agent.git
cd embedded-network-agent
./deploy/pi-setup.sh           # packages, client venv, build, unit tests, systemd install
```

`pi-setup.sh` prints the model/OS/kernel/compiler lines: paste them into
`docs/pi-environment.md` (the plan requires recording them with every result).

## First contact from the laptop

```powershell
$env:NDA_HOST = "nda-pi.local"
nda status
nda ping -n 20
nda netinfo
nda diag default_route
nda diag gateway_tcp
```

**Milestone (week 1):** `nda status` shows real CPU temperature and uptime from the Pi.

If it times out:

1. On the Pi: `systemctl status nda-server` and `journalctl -u nda-server -n 20 -o cat`.
2. On the Pi: `ss -ltnup | grep 500` — should show TCP 5000 and UDP 5001 on `0.0.0.0`.
3. Windows Firewall does **not** matter for outgoing connections, but if UDP replies never
   arrive, allow inbound UDP for Python: Windows may drop the echoed datagrams.
4. Pi OS Lite has no firewall by default; if you added `ufw`, allow 5000/tcp and 5001/udp.

## Updating after a code change

```bash
# on the Pi
cd ~/embedded-network-agent && git pull && ./deploy/install.sh
```

## Wi-Fi vs Ethernet

Run the benchmark matrix on Ethernet first and treat it as the primary data set; run it
again on Wi-Fi as the comparison. Wi-Fi latency is dominated by the radio (power save,
contention, retries), so Wi-Fi-only numbers mostly measure the access point, not this code.

The Pi 3B's Wi-Fi enables power saving by default, which adds tens of ms of latency
jitter. Record which setting you tested with; to disable it for a run:

```bash
sudo iw dev wlan0 set power_save off    # resets on reboot
```
