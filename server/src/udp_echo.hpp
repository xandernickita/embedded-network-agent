// UDP benchmark datagram validation (docs/PROTOCOL.md section 2).
#pragma once

#include <cstddef>
#include <cstring>

namespace nda {

inline constexpr std::size_t kUdpHeader = 16;
inline constexpr std::size_t kUdpMax = 1472;  // 1500 MTU - 20 IPv4 - 8 UDP: never fragments
inline constexpr char kUdpMagic[4] = {'N', 'D', 'A', '1'};

inline bool valid_bench_datagram(const char* data, std::size_t len) {
    return len >= kUdpHeader && len <= kUdpMax && std::memcmp(data, kUdpMagic, 4) == 0;
}

}  // namespace nda
