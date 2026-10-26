#!/usr/bin/env bash
# Build, unit-test and (re)install the server as a systemd service. Run ON THE PI from
# the repo root. Safe to re-run after every `git pull`.
set -euo pipefail
cd "$(dirname "$0")/.."

# A Pi 3B has 1 GB RAM; -j2 avoids swapping while compiling the JSON-heavy units.
cmake -S server -B server/build -DCMAKE_BUILD_TYPE=Release -DNDA_WERROR=ON
cmake --build server/build -j2
ctest --test-dir server/build --output-on-failure

sudo install -m 0755 server/build/nda-server /usr/local/bin/nda-server
sudo install -m 0644 deploy/nda-server.service /etc/systemd/system/nda-server.service
sudo systemctl daemon-reload
sudo systemctl enable --now nda-server
sudo systemctl restart nda-server
sleep 1
systemctl --no-pager --lines=5 status nda-server
echo
echo "Logs: journalctl -u nda-server -f -o cat"
