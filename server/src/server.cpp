#include "server.hpp"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cerrno>
#include <chrono>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

#include "framing.hpp"
#include "log.hpp"
#include "protocol.hpp"
#include "udp_echo.hpp"

namespace nda {
namespace {

using Clock = std::chrono::steady_clock;

// Stop reading from a client whose replies are piling up (it isn't reading). Resumes
// once the backlog drains, so one slow client can't make the server buffer without bound.
constexpr std::size_t kMaxPendingOut = 1 << 20;

struct Client {
    int fd = -1;
    std::string peer;
    FrameDecoder decoder;
    std::string out;
    std::size_t out_pos = 0;
    Clock::time_point last_activity = Clock::now();
    bool close_after_flush = false;
    bool dead = false;

    std::size_t pending() const { return out.size() - out_pos; }
};

std::string peer_name(const sockaddr_in& sa) {
    char buf[INET_ADDRSTRLEN] = {};
    inet_ntop(AF_INET, &sa.sin_addr, buf, sizeof buf);
    return std::string(buf) + ":" + std::to_string(ntohs(sa.sin_port));
}

int make_socket(int type, const ServerConfig& cfg, std::uint16_t port, std::uint16_t& bound_port) {
    const int fd = socket(AF_INET, type | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (fd < 0) return -1;
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);

    sockaddr_in sa{};
    sa.sin_family = AF_INET;
    sa.sin_port = htons(port);
    if (inet_pton(AF_INET, cfg.bind_address.c_str(), &sa.sin_addr) != 1 ||
        bind(fd, reinterpret_cast<sockaddr*>(&sa), sizeof sa) != 0 || (type == SOCK_STREAM && listen(fd, 64) != 0)) {
        const int saved = errno;
        close(fd);
        errno = saved;
        return -1;
    }
    socklen_t len = sizeof sa;
    getsockname(fd, reinterpret_cast<sockaddr*>(&sa), &len);
    bound_port = ntohs(sa.sin_port);
    return fd;
}

// Sends as much of the client's backlog as the kernel accepts right now.
void flush(Client& c, Metrics& m) {
    while (c.pending() > 0) {
        const ssize_t n = send(c.fd, c.out.data() + c.out_pos, c.pending(), MSG_NOSIGNAL);
        if (n > 0) {
            c.out_pos += static_cast<std::size_t>(n);
            m.bytes_tx += static_cast<std::uint64_t>(n);
            continue;
        }
        if (n < 0 && errno == EINTR) continue;
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) return;
        c.dead = true;  // EPIPE / ECONNRESET: peer is gone
        return;
    }
    c.out.clear();
    c.out_pos = 0;
    if (c.close_after_flush) c.dead = true;
}

void queue(Client& c, const std::string& payload) { c.out += encode_frame(payload); }

void on_readable(Client& c, Dispatcher& dispatch, Metrics& m) {
    char buf[65536];
    for (;;) {
        const ssize_t n = recv(c.fd, buf, sizeof buf, 0);
        if (n > 0) {
            m.bytes_rx += static_cast<std::uint64_t>(n);
            c.last_activity = Clock::now();
            c.decoder.feed(buf, static_cast<std::size_t>(n));
            if (static_cast<std::size_t>(n) < sizeof buf) break;
            continue;
        }
        if (n == 0) {  // orderly shutdown from the peer
            c.dead = c.pending() == 0;
            c.close_after_flush = true;
            break;
        }
        if (errno == EINTR) continue;
        if (errno != EAGAIN && errno != EWOULDBLOCK) c.dead = true;
        break;
    }

    while (auto payload = c.decoder.next()) queue(c, dispatch.handle(*payload));

    if (c.decoder.error() != FrameError::None && !c.close_after_flush) {
        const bool empty = c.decoder.error() == FrameError::Empty;
        ++m.errors_total;
        queue(c, error_response(nullptr, empty ? "BAD_FRAME" : "FRAME_TOO_LARGE",
                                empty ? "zero-length frame" : "frame exceeds 65536 bytes"));
        c.close_after_flush = true;
        log_event("warn", "frame_error", {{"peer", c.peer}, {"error", empty ? "BAD_FRAME" : "FRAME_TOO_LARGE"}});
    }
}

void serve_udp(int fd, Metrics& m) {
    char buf[2048];
    for (;;) {
        sockaddr_in from{};
        socklen_t len = sizeof from;
        const ssize_t n = recvfrom(fd, buf, sizeof buf, 0, reinterpret_cast<sockaddr*>(&from), &len);
        if (n < 0) return;  // EAGAIN: drained
        ++m.udp_datagrams_rx;
        if (!valid_bench_datagram(buf, static_cast<std::size_t>(n))) {
            ++m.udp_datagrams_invalid;
            continue;
        }
        if (sendto(fd, buf, static_cast<std::size_t>(n), 0, reinterpret_cast<sockaddr*>(&from), len) == n)
            ++m.udp_datagrams_tx;
    }
}

}  // namespace

int run_server(const ServerConfig& cfg, const std::atomic<bool>& stop) {
    std::uint16_t tcp_port = 0, udp_port = 0;
    const int lfd = make_socket(SOCK_STREAM, cfg, cfg.tcp_port, tcp_port);
    if (lfd < 0) {
        log_event("error", "bind_failed", {{"proto", "tcp"}, {"port", cfg.tcp_port}, {"error", std::strerror(errno)}});
        return 1;
    }
    const int ufd = make_socket(SOCK_DGRAM, cfg, cfg.udp_port, udp_port);
    if (ufd < 0) {
        log_event("error", "bind_failed", {{"proto", "udp"}, {"port", cfg.udp_port}, {"error", std::strerror(errno)}});
        close(lfd);
        return 1;
    }

    Telemetry telemetry(cfg.telemetry_paths);
    Metrics metrics;
    Dispatcher dispatch(telemetry, metrics);
    std::vector<std::unique_ptr<Client>> clients;

    log_event("info", "listening",
              {{"bind", cfg.bind_address}, {"tcp_port", tcp_port}, {"udp_port", udp_port}, {"max_clients", cfg.max_clients}});

    std::vector<pollfd> fds;
    while (!stop.load()) {
        fds.clear();
        fds.push_back({lfd, POLLIN, 0});
        fds.push_back({ufd, POLLIN, 0});
        for (const auto& c : clients) {
            short ev = 0;
            if (!c->close_after_flush && c->pending() < kMaxPendingOut) ev |= POLLIN;
            if (c->pending() > 0) ev |= POLLOUT;
            fds.push_back({c->fd, ev, 0});
        }

        const int ready = poll(fds.data(), fds.size(), 1000);
        if (ready < 0 && errno != EINTR) {
            log_event("error", "poll_failed", {{"error", std::strerror(errno)}});
            break;
        }

        if (ready > 0) {
            if (fds[1].revents & POLLIN) serve_udp(ufd, metrics);

            // Clients first (their indices in `fds` match `clients`), then accept new ones.
            for (std::size_t i = 0; i < clients.size(); ++i) {
                Client& c = *clients[i];
                const short re = fds[i + 2].revents;
                if (re & (POLLERR | POLLNVAL)) c.dead = true;
                if (!c.dead && (re & (POLLIN | POLLHUP))) on_readable(c, dispatch, metrics);
                if (!c.dead && c.pending() > 0) flush(c, metrics);
                if (!c.dead && c.close_after_flush && c.pending() == 0) c.dead = true;
            }

            if (fds[0].revents & POLLIN) {
                for (;;) {
                    sockaddr_in sa{};
                    socklen_t len = sizeof sa;
                    const int fd = accept4(lfd, reinterpret_cast<sockaddr*>(&sa), &len, SOCK_NONBLOCK | SOCK_CLOEXEC);
                    if (fd < 0) break;
                    if (static_cast<int>(clients.size()) >= cfg.max_clients) {
                        const std::string busy = encode_frame(error_response(nullptr, "SERVER_BUSY", "too many clients"));
                        (void)send(fd, busy.data(), busy.size(), MSG_NOSIGNAL);
                        close(fd);
                        ++metrics.errors_total;
                        log_event("warn", "client_rejected", {{"peer", peer_name(sa)}, {"reason", "max_clients"}});
                        continue;
                    }
                    int one = 1;
                    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);  // request/response: don't batch
                    auto c = std::make_unique<Client>();
                    c->fd = fd;
                    c->peer = peer_name(sa);
                    ++metrics.clients_total;
                    log_event("info", "client_connected", {{"peer", c->peer}});
                    clients.push_back(std::move(c));
                }
            }
        }

        // Idle timeout and reaping.
        const auto now = Clock::now();
        for (auto& c : clients) {
            if (!c->dead && now - c->last_activity > std::chrono::seconds(cfg.idle_timeout_s)) {
                c->dead = true;
                log_event("info", "client_idle_timeout", {{"peer", c->peer}});
            }
        }
        for (auto it = clients.begin(); it != clients.end();) {
            if ((*it)->dead) {
                close((*it)->fd);
                log_event("info", "client_disconnected", {{"peer", (*it)->peer}});
                it = clients.erase(it);
            } else {
                ++it;
            }
        }
        metrics.clients_active = clients.size();
    }

    for (auto& c : clients) close(c->fd);
    close(lfd);
    close(ufd);
    log_event("info", "stopped", metrics.to_json());
    return 0;
}

}  // namespace nda
