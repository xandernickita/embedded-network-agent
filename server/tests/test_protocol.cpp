#include "../src/protocol.hpp"
#include "check.hpp"

using nlohmann::json;

namespace {

const nda::Telemetry& pi_telemetry() {
    static nda::Telemetry t({NDA_FIXTURES "/pi3b/proc", NDA_FIXTURES "/pi3b/sys"});
    return t;
}

json call(const std::string& payload) {
    static nda::Metrics m;
    nda::Dispatcher d(pi_telemetry(), m);
    return json::parse(d.handle(payload));
}

json req(const std::string& command, json args = json::object(), json id = 7) {
    return {{"version", 1}, {"request_id", id}, {"command", command}, {"args", args}};
}

std::string code_of(const json& r) { return r["error"]["code"].get<std::string>(); }

}  // namespace

TEST("protocol: ping echoes request_id and returns a server timestamp") {
    auto r = call(req("ping").dump());
    CHECK_EQ(r["status"], "ok");
    CHECK_EQ(r["request_id"], 7);
    CHECK_EQ(r["version"], 1);
    CHECK(r["data"]["server_time_ns"].is_number_integer());
}

TEST("protocol: args is optional") {
    auto r = call(R"({"version":1,"request_id":1,"command":"ping"})");
    CHECK_EQ(r["status"], "ok");
}

TEST("protocol: get_status reads telemetry") {
    auto d = call(req("get_status").dump())["data"];
    CHECK_EQ(d["hostname"], "nda-pi");
    CHECK_EQ(d["cpu_temperature_c"], 48.2);
    CHECK_EQ(d["memory_percent"], 31.4);
    CHECK_EQ(d["uptime_seconds"], 52320.4);
    CHECK_EQ(d["load_avg"][0], 0.12);
    CHECK_EQ(d["kernel"], "6.12.25+rpt-rpi-v8");
}

TEST("protocol: echo returns payload unchanged") {
    auto r = call(req("echo", {{"payload", "abcé"}}).dump());
    CHECK_EQ(r["data"]["payload"], "abcé");
}

TEST("protocol: echo rejects missing or oversize payload") {
    CHECK_EQ(code_of(call(req("echo").dump())), "INVALID_ARGS");
    CHECK_EQ(code_of(call(req("echo", {{"payload", std::string(60001, 'x')}}).dump())), "INVALID_ARGS");
    CHECK_EQ(call(req("echo", {{"payload", std::string(60000, 'x')}}).dump())["status"], "ok");
}

TEST("protocol: malformed JSON is reported with null request_id") {
    auto r = call("{not json");
    CHECK_EQ(r["status"], "error");
    CHECK_EQ(code_of(r), "MALFORMED_JSON");
    CHECK(r["request_id"].is_null());
    CHECK_EQ(code_of(call("[1,2,3]")), "MALFORMED_JSON");
}

TEST("protocol: request_id must be a non-negative 53-bit integer") {
    CHECK_EQ(code_of(call(R"({"version":1,"command":"ping"})")), "INVALID_REQUEST");
    CHECK_EQ(code_of(call(req("ping", json::object(), "7").dump())), "INVALID_REQUEST");
    CHECK_EQ(code_of(call(req("ping", json::object(), -1).dump())), "INVALID_REQUEST");
    CHECK_EQ(code_of(call(req("ping", json::object(), 1.5).dump())), "INVALID_REQUEST");
    CHECK_EQ(code_of(call(req("ping", json::object(), 9007199254740992ULL).dump())), "INVALID_REQUEST");
    CHECK_EQ(call(req("ping", json::object(), 9007199254740991ULL).dump())["status"], "ok");
}

TEST("protocol: version check echoes the request_id") {
    auto r = call(R"({"version":2,"request_id":99,"command":"ping"})");
    CHECK_EQ(code_of(r), "UNSUPPORTED_VERSION");
    CHECK_EQ(r["request_id"], 99);
    CHECK_EQ(code_of(call(R"({"request_id":1,"command":"ping"})")), "INVALID_REQUEST");
}

TEST("protocol: unknown command and bad args") {
    CHECK_EQ(code_of(call(req("reboot").dump())), "UNKNOWN_COMMAND");
    CHECK_EQ(code_of(call(R"({"version":1,"request_id":1,"command":5})")), "INVALID_REQUEST");
    CHECK_EQ(code_of(call(R"({"version":1,"request_id":1,"command":"ping","args":[]})")), "INVALID_REQUEST");
}

TEST("protocol: run_diagnostic accepts only allowlisted tests") {
    CHECK_EQ(code_of(call(req("run_diagnostic").dump())), "INVALID_ARGS");
    CHECK_EQ(code_of(call(req("run_diagnostic", {{"test", "rm -rf /"}}).dump())), "INVALID_ARGS");
    auto r = call(req("run_diagnostic", {{"test", "default_route"}}).dump());
    CHECK_EQ(r["data"]["gateway"], "192.168.1.1");
    CHECK_EQ(r["data"]["interface"], "wlan0");
    auto ls = call(req("run_diagnostic", {{"test", "link_stats"}}).dump());
    CHECK_EQ(ls["data"]["interfaces"]["wlan0"]["rx_errors"], 104);
}

TEST("protocol: get_netinfo lists interfaces with counters") {
    auto list = call(req("get_netinfo").dump())["data"]["interfaces"];
    CHECK_EQ(list.size(), 2u);
    CHECK_EQ(list[1]["name"], "wlan0");
    CHECK_EQ(list[1]["mtu"], 1500);
    CHECK_EQ(list[1]["mac"], "b8:27:eb:12:34:56");
    CHECK_EQ(list[1]["rx_bytes"], 100);
}

TEST("protocol: metrics count requests and errors") {
    nda::Metrics m;
    nda::Dispatcher d(pi_telemetry(), m);
    d.handle(req("ping").dump());
    d.handle("garbage");
    CHECK_EQ(m.requests_total, 2u);
    CHECK_EQ(m.errors_total, 1u);
    auto r = json::parse(d.handle(req("get_metrics").dump()));
    CHECK_EQ(r["data"]["requests_total"], 3);
}

TEST("telemetry: missing files become null, not errors") {
    nda::Telemetry t({NDA_FIXTURES "/empty/proc", NDA_FIXTURES "/empty/sys"});
    nda::Metrics m;
    nda::Dispatcher d(t, m);
    auto r = json::parse(d.handle(req("get_status").dump()));
    CHECK_EQ(r["status"], "ok");
    CHECK(r["data"]["cpu_temperature_c"].is_null());
    CHECK(r["data"]["memory_percent"].is_null());
    auto route = json::parse(d.handle(req("run_diagnostic", {{"test", "default_route"}}).dump()));
    CHECK(route["data"]["gateway"].is_null());
    auto gw = json::parse(d.handle(req("run_diagnostic", {{"test", "gateway_tcp"}}).dump()));
    CHECK_EQ(gw["data"]["reachable"], false);
}
