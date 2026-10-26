#!/usr/bin/env bash
# One-time Pi preparation. Run ON THE PI after first SSH login:
#   git clone https://github.com/xandernickita/embedded-network-agent.git
#   cd embedded-network-agent && ./deploy/pi-setup.sh
set -euo pipefail

echo "==> Packages (compiler, CMake, JSON header, tc for netem, Python venv)"
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    build-essential cmake git nlohmann-json3-dev \
    iproute2 python3-venv python3-pip tcpdump

echo "==> Python client (so the benchmarks can also run Pi-side for loopback baselines)"
python3 -m venv .venv
.venv/bin/pip install -q -e "client[dev]"

echo "==> Build, test and install the server"
./deploy/install.sh

echo
echo "Done. Record these in docs/pi-environment.md for the report:"
echo "  model:  $(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo unknown)"
echo "  os:     $(. /etc/os-release && echo "$PRETTY_NAME")"
echo "  kernel: $(uname -r)"
echo "  arch:   $(uname -m)"
echo "  cmake:  $(cmake --version | head -1)"
echo "  g++:    $(g++ --version | head -1)"
