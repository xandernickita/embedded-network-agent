#include "protocol.hpp"

#include <stdexcept>

using nlohmann::json;

namespace nda {
namespace {

constexpr std::uint64_t kMaxRequestId = (std::uint64_t{1} << 53) - 1;

// Thrown by handlers to produce a documented error code instead of INTERNAL_ERROR.
struct ProtocolError : std::runtime_error {
    std::string code;
    ProtocolError(std::string c, const std::string& msg) : std::runtime_error(msg), code(std::move(c)) {}
};

std::string dump(const json& j) { return j.dump(-1, ' ', false, json::error_handler_t::replace); }

std::int64_t monotonic_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

}  // namespace

json Metrics::to_json() const {
    const double up = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    return {
        {"server_uptime_s", static_cast<std::int64_t>(up)},
        {"requests_total", requests_total},
        {"errors_total", errors_total},
        {"clients_active", clients_active},
        {"clients_total", clients_total},
        {"bytes_rx", bytes_rx},
        {"bytes_tx", bytes_tx},
        {"udp_datagrams_rx", udp_datagrams_rx},
        {"udp_datagrams_tx", udp_datagrams_tx},
        {"udp_datagrams_invalid", udp_datagrams_invalid},
    };
}

std::string error_response(const json& request_id, std::string_view code, std::string_view message) {
    return dump({
        {"version", kProtocolVersion},
        {"request_id", request_id},
        {"status", "error"},
        {"error", {{"code", code}, {"message", message}}},
    });
}

std::string Dispatcher::handle(std::string_view payload) {
    ++metrics_.requests_total;
    auto fail = [this](const json& id, std::string_view code, std::string_view msg) {
        ++metrics_.errors_total;
        return error_response(id, code, msg);
    };

    const json req = json::parse(payload, nullptr, /*allow_exceptions=*/false);
    if (req.is_discarded()) return fail(nullptr, "MALFORMED_JSON", "payload is not valid JSON");
    if (!req.is_object()) return fail(nullptr, "MALFORMED_JSON", "payload must be a JSON object");

    // request_id first, so every later error can echo it.
    auto id_it = req.find("request_id");
    if (id_it == req.end() || !id_it->is_number_integer() || id_it->get<std::int64_t>() < 0 ||
        id_it->get<std::uint64_t>() > kMaxRequestId)
        return fail(nullptr, "INVALID_REQUEST", "request_id must be an integer in 0..2^53-1");
    const json id = *id_it;

    auto ver = req.find("version");
    if (ver == req.end() || !ver->is_number_integer()) return fail(id, "INVALID_REQUEST", "version must be an integer");
    if (ver->get<std::int64_t>() != kProtocolVersion) return fail(id, "UNSUPPORTED_VERSION", "only version 1 is supported");

    auto cmd = req.find("command");
    if (cmd == req.end() || !cmd->is_string()) return fail(id, "INVALID_REQUEST", "command must be a string");

    json args = json::object();
    if (auto a = req.find("args"); a != req.end()) {
        if (!a->is_object()) return fail(id, "INVALID_REQUEST", "args must be an object");
        args = *a;
    }

    try {
        json data = run(cmd->get<std::string>(), args);
        return dump({{"version", kProtocolVersion}, {"request_id", id}, {"status", "ok"}, {"data", std::move(data)}});
    } catch (const ProtocolError& e) {
        return fail(id, e.code, e.what());
    } catch (const std::exception& e) {
        return fail(id, "INTERNAL_ERROR", e.what());
    }
}

json Dispatcher::run(const std::string& command, const json& args) {
    if (command == "ping") return {{"server_time_ns", monotonic_ns()}};

    if (command == "echo") {
        auto p = args.find("payload");
        if (p == args.end() || !p->is_string()) throw ProtocolError("INVALID_ARGS", "echo needs a string 'payload'");
        if (p->get_ref<const std::string&>().size() > kMaxEchoPayload)
            throw ProtocolError("INVALID_ARGS", "echo payload is limited to 60000 bytes");
        return {{"payload", *p}};
    }

    if (command == "get_status") return telemetry_.status();
    if (command == "get_netinfo") return telemetry_.netinfo();
    if (command == "get_metrics") return metrics_.to_json();

    if (command == "run_diagnostic") {
        auto t = args.find("test");
        if (t == args.end() || !t->is_string()) throw ProtocolError("INVALID_ARGS", "run_diagnostic needs a string 'test'");
        const auto& test = t->get_ref<const std::string&>();
        if (test == "default_route") return telemetry_.default_route();
        if (test == "link_stats") return telemetry_.link_stats();
        if (test == "gateway_tcp") return gateway_tcp(telemetry_.default_route());
        throw ProtocolError("INVALID_ARGS", "unknown test '" + test + "' (default_route, link_stats, gateway_tcp)");
    }

    throw ProtocolError("UNKNOWN_COMMAND", "no command '" + command + "'");
}

}  // namespace nda
