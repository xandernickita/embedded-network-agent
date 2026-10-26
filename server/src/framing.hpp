// Length-prefixed framing for the TCP command channel (docs/PROTOCOL.md section 1).
#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

namespace nda {

inline constexpr std::size_t kHeaderSize = 4;
inline constexpr std::uint32_t kMaxFrame = 65536;

// Prepends the 4-byte big-endian length header. Caller guarantees 1 <= size <= kMaxFrame.
std::string encode_frame(std::string_view payload);

enum class FrameError { None, Empty, TooLarge };

// Accumulates bytes from recv() and hands out complete payloads.
// After an error the decoder is poisoned: the stream position is lost, so the
// connection has to be closed.
class FrameDecoder {
   public:
    void feed(const char* data, std::size_t len);

    // Next complete payload, or nullopt if more bytes are needed or an error occurred.
    std::optional<std::string> next();

    FrameError error() const { return error_; }
    std::size_t buffered() const { return buf_.size() - pos_; }

   private:
    std::string buf_;
    std::size_t pos_ = 0;
    FrameError error_ = FrameError::None;
};

}  // namespace nda
