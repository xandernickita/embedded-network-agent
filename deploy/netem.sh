#!/usr/bin/env bash
# Inject loss / delay / reordering on the Pi's interface with tc-netem, so the UDP
# benchmark has something to detect. A quiet LAN shows ~0 % loss, which proves nothing
# about the measurement code; a known impairment lets the report compare measured vs
# configured.
#
#   ./deploy/netem.sh wlan0 loss 5%                 5 % random loss
#   ./deploy/netem.sh wlan0 delay 20ms 5ms          20 ms +/- 5 ms
#   ./deploy/netem.sh wlan0 reorder 25% 50%         reorder (needs a delay to act on)
#   ./deploy/netem.sh wlan0 show
#   ./deploy/netem.sh wlan0 clear
#
# netem acts on EGRESS only: it impairs the Pi's replies, so a round trip sees the
# configured rate once. ALWAYS `clear` when done; it does not survive a reboot.
set -euo pipefail

iface=${1:?interface, e.g. wlan0 or eth0}
action=${2:?loss | delay | reorder | show | clear}
shift 2

case "$action" in
  loss)    sudo tc qdisc replace dev "$iface" root netem loss "${1:?percent}" ;;
  delay)   sudo tc qdisc replace dev "$iface" root netem delay "${1:?ms}" "${2:-0ms}" ;;
  reorder) sudo tc qdisc replace dev "$iface" root netem delay 10ms reorder "${1:?percent}" "${2:-50%}" ;;
  show)    tc qdisc show dev "$iface"; exit 0 ;;
  clear)   sudo tc qdisc del dev "$iface" root 2>/dev/null || true; tc qdisc show dev "$iface"; exit 0 ;;
  *)       echo "unknown action: $action" >&2; exit 2 ;;
esac
tc qdisc show dev "$iface"
