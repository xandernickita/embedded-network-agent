#include "framing.hpp"

namespace nda {

std::string encode_frame(std::string_view payload) {
    const auto n = static_cast<std::uint32_t>(payload.size());
    std::string out;
    out.reserve(kHeaderSize + payload.size());
    out.push_back(static_cast<char>((n >> 24) & 0xFF));
    out.push_back(static_cast<char>((n >> 16) & 0xFF));
    out.push_back(static_cast<char>((n >> 8) & 0xFF));
    out.push_back(static_cast<char>(n & 0xFF));
    out.append(payload);
    return out;
}

void FrameDecoder::feed(const char* data, std::size_t len) {
    if (error_ != FrameError::None) return;
    // Compact consumed bytes before growing, so a long-lived connection doesn't leak.
    if (pos_ > 0 && pos_ >= buf_.size() / 2) {
        buf_.erase(0, pos_);
        pos_ = 0;
    }
    buf_.append(data, len);
}

std::optional<std::string> FrameDecoder::next() {
    if (error_ != FrameError::None) return std::nullopt;
    if (buffered() < kHeaderSize) return std::nullopt;

    const auto* p = reinterpret_cast<const unsigned char*>(buf_.data() + pos_);
    const std::uint32_t n = (std::uint32_t{p[0]} << 24) | (std::uint32_t{p[1]} << 16) |
                            (std::uint32_t{p[2]} << 8) | std::uint32_t{p[3]};
    if (n == 0) {
        error_ = FrameError::Empty;
        return std::nullopt;
    }
    if (n > kMaxFrame) {
        error_ = FrameError::TooLarge;
        return std::nullopt;
    }
    if (buffered() < kHeaderSize + n) return std::nullopt;

    std::string payload = buf_.substr(pos_ + kHeaderSize, n);
    pos_ += kHeaderSize + n;
    if (pos_ == buf_.size()) {
        buf_.clear();
        pos_ = 0;
    }
    return payload;
}

}  // namespace nda
