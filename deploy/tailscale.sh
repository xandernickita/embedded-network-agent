#!/usr/bin/env bash
# Join the Pi to your Tailscale network so the laptop can reach the agent from any network.
# Run ON THE PI (needs the Pi's own internet connection). Safe to re-run.
#
#   ./deploy/tailscale.sh
#
# The first run prints a login URL: open it on the laptop and approve the device.
# The agent itself is unchanged: it already listens on all interfaces, including tailscale0.
# See docs/remote-access.md for naming, benchmarking rules and security notes.
set -euo pipefail

if ! command -v tailscale >/dev/null 2>&1; then
    echo "==> Installing Tailscale (official package repository)"
    curl -fsSL https://tailscale.com/install.sh | sh
fi

sudo systemctl enable --now tailscaled

echo "==> Bringing the tunnel up as 'nda-pi'"
# --hostname pins the tailnet name, so MagicDNS resolves `nda-pi` whatever the OS hostname.
sudo tailscale up --hostname=nda-pi

ip4=$(tailscale ip -4)
echo
tailscale status
echo
echo "Tailnet address: ${ip4}"
echo "tailscale0 MTU:  $(cat /sys/class/net/tailscale0/mtu)   (UDP payloads above $(( $(cat /sys/class/net/tailscale0/mtu) - 28 )) bytes fragment)"
echo
echo "From the laptop (with Tailscale running), anywhere:"
echo "  nda --host nda-pi status          # MagicDNS name"
echo "  nda --host ${ip4} status"
echo
echo "Benchmarks: use --host nda-pi.local for the LAN path and --host nda-pi --link tailscale for the tunnel."
