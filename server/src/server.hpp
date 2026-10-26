// Single-threaded poll() event loop serving the TCP command channel and the UDP echo
// endpoint. See docs/architecture.md for why one thread is enough on a Pi 3B.
#pragma once

#include <atomic>
#include <cstdint>
#include <string>

#include "telemetry.hpp"

namespace nda {

struct ServerConfig {
    std::string bind_address = "0.0.0.0";
    std::uint16_t tcp_port = 5000;  // 0 = pick a free port (tests)
    std::uint16_t udp_port = 5001;  // 0 = pick a free port (tests)
    int max_clients = 32;
    int idle_timeout_s = 60;
    TelemetryPaths telemetry_paths{};
};

// Runs until `stop` becomes true. Returns a process exit code.
int run_server(const ServerConfig& cfg, const std::atomic<bool>& stop);

}  // namespace nda
