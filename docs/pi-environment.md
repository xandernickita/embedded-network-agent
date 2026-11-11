# Test environment

Fill in from the output of `deploy/pi-setup.sh` on first bring-up. Every benchmark
result in `benchmarks/results/` was measured on this setup unless its CSV says otherwise.

| Item | Value |
|---|---|
| Pi model | Raspberry Pi 3 Model B Plus Rev 1.4 |
| OS | Debian GNU/Linux 13 (Trixie), Raspberry Pi OS Lite (64-bit) |
| Kernel | 6.18.50+rpt-rpi-v8 |
| Architecture | aarch64 |
| Compiler | g++ (Debian 14.2.0-19) 14.2.0 |
| CMake | 3.31.6 |
| Power | `vcgencmd get_throttled` = 0x0 at bring-up and before the benchmark session |
| Laptop OS | Windows 11 Enterprise v23H2 |
| Laptop Python | Python 3.14.6 |
| Laptop network | **Wi-Fi for every benchmark** (every path includes the laptop's radio) |
| Network (Ethernet) | gigabit PHY behind USB 2.0 (~300 Mb/s practical) |
| Network (Wi-Fi) | 5 GHz, 5785 MHz (ch 157), signal −18 dBm, power_save **on** (recorded after the runs; same router config) |
| Network (Tailscale) | tailscale0 MTU 1280; **direct** path (`tailscale ping nda-pi` → via 192.168.1.180:41641), over the Pi's Ethernet |
| Memory cgroup | Disabled by the stock Pi kernel (`cgroup.controllers`: cpuset cpu io pids), so systemd `MemoryMax` is not enforced |
