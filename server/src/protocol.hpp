// Request validation and command dispatch (docs/PROTOCOL.md section 1).
// Pure logic: takes one decoded payload, returns one response payload. No sockets here,
// which is what lets server/tests exercise every error path without a network.
#pragma once

#include <nlohmann/json.hpp>
#include <chrono>
#include <cstdint>
#include <string>
#include <string_view>

#include "telemetry.hpp"

namespace nda {

inline constexpr int kProtocolVersion = 1;
inline constexpr std::size_t kMaxEchoPayload = 60000;

struct Metrics {
    std::chrono::steady_clock::time_point started = std::chrono::steady_clock::now();
    std::uint64_t requests_total = 0;
    std::uint64_t errors_total = 0;
    std::uint64_t clients_active = 0;
    std::uint64_t clients_total = 0;
    std::uint64_t bytes_rx = 0;
    std::uint64_t bytes_tx = 0;
    std::uint64_t udp_datagrams_rx = 0;
    std::uint64_t udp_datagrams_tx = 0;
    std::uint64_t udp_datagrams_invalid = 0;

    nlohmann::json to_json() const;
};

// Builds an error response. `request_id` may be null.
std::string error_response(const nlohmann::json& request_id, std::string_view code, std::string_view message);

class Dispatcher {
   public:
    Dispatcher(const Telemetry& telemetry, Metrics& metrics) : telemetry_(telemetry), metrics_(metrics) {}

    // One request payload in, one response payload out. Never throws.
    std::string handle(std::string_view payload);

   private:
    nlohmann::json run(const std::string& command, const nlohmann::json& args);

    const Telemetry& telemetry_;
    Metrics& metrics_;
};

}  // namespace nda
