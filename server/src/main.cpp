#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include "server.hpp"

#ifndef NDA_VERSION
#define NDA_VERSION "dev"
#endif

namespace {

std::atomic<bool> g_stop{false};

void on_signal(int) { g_stop.store(true); }

void usage() {
    std::puts(
        "usage: nda-server [options]\n"
        "  --bind ADDR          IPv4 address to bind (default 0.0.0.0)\n"
        "  --tcp-port N         command port (default 5000, 0 = any free port)\n"
        "  --udp-port N         UDP echo port (default 5001, 0 = any free port)\n"
        "  --max-clients N      concurrent TCP clients (default 32)\n"
        "  --idle-timeout S     close idle TCP clients after S seconds (default 60)\n"
        "  --proc-root DIR      read telemetry from DIR instead of /proc (tests)\n"
        "  --sys-root DIR       read telemetry from DIR instead of /sys (tests)\n"
        "  --version            print version and exit");
}

bool parse_int(const char* s, long lo, long hi, long& out) {
    char* end = nullptr;
    out = std::strtol(s, &end, 10);
    return end != s && *end == '\0' && out >= lo && out <= hi;
}

}  // namespace

int main(int argc, char** argv) {
    nda::ServerConfig cfg;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        auto value = [&]() -> const char* {
            if (i + 1 >= argc) {
                std::fprintf(stderr, "missing value for %s\n", a.c_str());
                std::exit(2);
            }
            return argv[++i];
        };
        long n = 0;
        if (a == "--help" || a == "-h") {
            usage();
            return 0;
        } else if (a == "--version") {
            std::puts(NDA_VERSION);
            return 0;
        } else if (a == "--bind") {
            cfg.bind_address = value();
        } else if (a == "--tcp-port" && parse_int(value(), 0, 65535, n)) {
            cfg.tcp_port = static_cast<std::uint16_t>(n);
        } else if (a == "--udp-port" && parse_int(value(), 0, 65535, n)) {
            cfg.udp_port = static_cast<std::uint16_t>(n);
        } else if (a == "--max-clients" && parse_int(value(), 1, 1000, n)) {
            cfg.max_clients = static_cast<int>(n);
        } else if (a == "--idle-timeout" && parse_int(value(), 1, 86400, n)) {
            cfg.idle_timeout_s = static_cast<int>(n);
        } else if (a == "--proc-root") {
            cfg.telemetry_paths.proc = value();
        } else if (a == "--sys-root") {
            cfg.telemetry_paths.sys = value();
        } else {
            std::fprintf(stderr, "bad argument: %s\n\n", a.c_str());
            usage();
            return 2;
        }
    }

    // No SA_RESTART: a signal must interrupt poll() so shutdown is immediate.
    struct sigaction sa {};
    sa.sa_handler = on_signal;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT, &sa, nullptr);
    sigaction(SIGTERM, &sa, nullptr);
    std::signal(SIGPIPE, SIG_IGN);

    return nda::run_server(cfg, g_stop);
}
