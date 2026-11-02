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
| Power | `vcgencmd get_throttled` = 0x0 at bring-up (check again before each benchmark run) |
| Laptop OS | Windows 11 Enterprise v23H2 |
| Laptop Python | Python 3.14.6 |
| Network (Ethernet) | gigabit PHY behind USB 2.0 (~300 Mb/s practical) |
| Network (Wi-Fi) | 802.11ac dual-band; record the band per run from `iw dev wlan0 link` (`freq:`) and power_save on/off |
