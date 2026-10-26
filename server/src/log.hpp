// Structured logs: one JSON object per line on stderr. systemd's journal captures it on
// the Pi (`journalctl -u nda-server -o cat | jq`).
#pragma once

#include <nlohmann/json.hpp>
#include <chrono>
#include <cstdio>
#include <ctime>
#include <string_view>

namespace nda {

inline void log_event(std::string_view level, std::string_view event, nlohmann::json fields = nlohmann::json::object()) {
    using namespace std::chrono;
    const auto now = system_clock::now();
    const std::time_t t = system_clock::to_time_t(now);
    const auto ms = duration_cast<milliseconds>(now.time_since_epoch()).count() % 1000;
    std::tm tm{};
    gmtime_r(&t, &tm);
    char ts[64];
    std::snprintf(ts, sizeof ts, "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
                  tm.tm_hour, tm.tm_min, tm.tm_sec, static_cast<int>(ms));
    fields["ts"] = ts;
    fields["level"] = level;
    fields["event"] = event;
    const std::string line = fields.dump(-1, ' ', false, nlohmann::json::error_handler_t::replace) + "\n";
    std::fwrite(line.data(), 1, line.size(), stderr);
    std::fflush(stderr);
}

}  // namespace nda
