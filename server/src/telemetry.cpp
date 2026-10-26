#include "telemetry.hpp"

#include <arpa/inet.h>
#include <fcntl.h>
#include <ifaddrs.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <map>
#include <optional>
#include <sstream>
#include <vector>

namespace fs = std::filesystem;
using nlohmann::json;

namespace nda {
namespace {

std::optional<std::string> read_first_line(const std::string& path) {
    std::ifstream f(path);
    if (!f) return std::nullopt;
    std::string line;
    if (!std::getline(f, line)) return std::nullopt;
    return line;
}

std::optional<long long> read_ll(const std::string& path) {
    auto line = read_first_line(path);
    if (!line) return std::nullopt;
    try {
        return std::stoll(*line);
    } catch (...) {
        return std::nullopt;
    }
}

json opt(const std::optional<std::string>& v) { return v ? json(*v) : json(nullptr); }
json opt(const std::optional<long long>& v) { return v ? json(*v) : json(nullptr); }

double round1(double v) { return std::round(v * 10.0) / 10.0; }

std::map<std::string, std::vector<std::string>> ipv4_by_interface() {
    std::map<std::string, std::vector<std::string>> out;
    ifaddrs* list = nullptr;
    if (getifaddrs(&list) != 0) return out;
    for (auto* a = list; a != nullptr; a = a->ifa_next) {
        if (a->ifa_addr == nullptr || a->ifa_addr->sa_family != AF_INET) continue;
        char buf[INET_ADDRSTRLEN] = {};
        const auto* sin = reinterpret_cast<const sockaddr_in*>(a->ifa_addr);
        if (inet_ntop(AF_INET, &sin->sin_addr, buf, sizeof buf) != nullptr) out[a->ifa_name].emplace_back(buf);
    }
    freeifaddrs(list);
    return out;
}

std::vector<std::string> interface_names(const std::string& sys) {
    std::vector<std::string> names;
    std::error_code ec;
    for (const auto& e : fs::directory_iterator(sys + "/class/net", ec)) names.push_back(e.path().filename().string());
    std::sort(names.begin(), names.end());
    return names;
}

const char* kCounters[] = {"rx_bytes",   "tx_bytes",   "rx_packets", "tx_packets",
                           "rx_errors",  "tx_errors",  "rx_dropped", "tx_dropped"};

}  // namespace

json Telemetry::status() const {
    json d;
    d["hostname"] = opt(read_first_line(paths_.proc + "/sys/kernel/hostname"));
    d["kernel"] = opt(read_first_line(paths_.proc + "/sys/kernel/osrelease"));

    d["uptime_seconds"] = nullptr;
    if (auto up = read_first_line(paths_.proc + "/uptime")) {
        try {
            d["uptime_seconds"] = round1(std::stod(*up));
        } catch (...) {
        }
    }

    d["cpu_temperature_c"] = nullptr;
    if (auto milli = read_ll(paths_.sys + "/class/thermal/thermal_zone0/temp")) d["cpu_temperature_c"] = round1(static_cast<double>(*milli) / 1000.0);

    d["load_avg"] = nullptr;
    if (auto la = read_first_line(paths_.proc + "/loadavg")) {
        std::istringstream in(*la);
        double a = 0, b = 0, c = 0;
        if (in >> a >> b >> c) d["load_avg"] = {a, b, c};
    }

    d["memory_total_kb"] = nullptr;
    d["memory_available_kb"] = nullptr;
    d["memory_percent"] = nullptr;
    std::ifstream mem(paths_.proc + "/meminfo");
    long long total = -1, avail = -1;
    for (std::string key; mem >> key;) {
        long long v = 0;
        mem >> v;
        if (key == "MemTotal:") total = v;
        if (key == "MemAvailable:") avail = v;
        mem.ignore(256, '\n');
    }
    if (total > 0 && avail >= 0) {
        d["memory_total_kb"] = total;
        d["memory_available_kb"] = avail;
        d["memory_percent"] = round1(100.0 * static_cast<double>(total - avail) / static_cast<double>(total));
    }
    return d;
}

json Telemetry::netinfo() const {
    const bool real_system = paths_.sys == "/sys";
    const auto ips = real_system ? ipv4_by_interface() : std::map<std::string, std::vector<std::string>>{};
    json list = json::array();
    for (const auto& name : interface_names(paths_.sys)) {
        const std::string base = paths_.sys + "/class/net/" + name;
        json i;
        i["name"] = name;
        i["operstate"] = opt(read_first_line(base + "/operstate"));
        i["mtu"] = opt(read_ll(base + "/mtu"));
        i["mac"] = opt(read_first_line(base + "/address"));
        auto it = ips.find(name);
        i["ipv4"] = it == ips.end() ? json::array() : json(it->second);
        for (const char* c : kCounters) i[c] = opt(read_ll(base + "/statistics/" + c));
        list.push_back(std::move(i));
    }
    return {{"interfaces", list}};
}

json Telemetry::default_route() const {
    std::ifstream f(paths_.proc + "/net/route");
    std::string line;
    std::getline(f, line);  // header
    while (std::getline(f, line)) {
        std::istringstream in(line);
        std::string iface, dest, gw;
        if (!(in >> iface >> dest >> gw)) continue;
        if (dest != "00000000") continue;
        // /proc/net/route stores the address as host-order hex of a network-order value.
        in_addr addr{};
        addr.s_addr = static_cast<in_addr_t>(std::stoul(gw, nullptr, 16));
        char buf[INET_ADDRSTRLEN] = {};
        inet_ntop(AF_INET, &addr, buf, sizeof buf);
        return {{"interface", iface}, {"gateway", buf}};
    }
    return {{"interface", nullptr}, {"gateway", nullptr}};
}

json Telemetry::link_stats() const {
    json out = json::object();
    for (const auto& name : interface_names(paths_.sys)) {
        json c;
        for (const char* k : kCounters) c[k] = opt(read_ll(paths_.sys + "/class/net/" + name + "/statistics/" + k));
        out[name] = c;
    }
    return {{"interfaces", out}};
}

json gateway_tcp(const json& route) {
    if (!route.contains("gateway") || route["gateway"].is_null()) return {{"gateway", nullptr}, {"reachable", false}};
    const std::string gw = route["gateway"].get<std::string>();
    sockaddr_in sa{};
    sa.sin_family = AF_INET;
    if (inet_pton(AF_INET, gw.c_str(), &sa.sin_addr) != 1) return {{"gateway", gw}, {"reachable", false}};

    for (int port : {53, 80, 443}) {
        sa.sin_port = htons(static_cast<uint16_t>(port));
        const int fd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
        if (fd < 0) continue;
        const auto t0 = std::chrono::steady_clock::now();
        int rc = connect(fd, reinterpret_cast<sockaddr*>(&sa), sizeof sa);
        bool ok = rc == 0;
        if (rc != 0 && errno == EINPROGRESS) {
            pollfd p{fd, POLLOUT, 0};
            if (poll(&p, 1, 500) == 1) {
                int err = 0;
                socklen_t len = sizeof err;
                getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &len);
                ok = err == 0;
            }
        }
        const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
        close(fd);
        if (ok) return {{"gateway", gw}, {"port", port}, {"connect_ms", std::round(ms * 1000.0) / 1000.0}};
    }
    return {{"gateway", gw}, {"reachable", false}};
}

}  // namespace nda
