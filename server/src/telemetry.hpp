// System telemetry read from /proc and /sys. Roots are injectable so tests can use a
// fake tree (server/tests/fixtures) and CI runners without a thermal zone still pass.
#pragma once

#include <nlohmann/json.hpp>
#include <string>

namespace nda {

struct TelemetryPaths {
    std::string proc = "/proc";
    std::string sys = "/sys";
};

class Telemetry {
   public:
    explicit Telemetry(TelemetryPaths paths = {}) : paths_(std::move(paths)) {}

    nlohmann::json status() const;          // get_status
    nlohmann::json netinfo() const;         // get_netinfo
    nlohmann::json default_route() const;   // run_diagnostic default_route
    nlohmann::json link_stats() const;      // run_diagnostic link_stats

   private:
    TelemetryPaths paths_;
};

// Times a TCP connect() to the default gateway (run_diagnostic gateway_tcp).
nlohmann::json gateway_tcp(const nlohmann::json& route);

}  // namespace nda
