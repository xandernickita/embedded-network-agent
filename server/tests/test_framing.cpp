#include "../src/framing.hpp"
#include "../src/udp_echo.hpp"
#include "check.hpp"

using nda::encode_frame;
using nda::FrameDecoder;
using nda::FrameError;

TEST("framing: header is big-endian payload length") {
    const std::string f = encode_frame("hello");
    CHECK_EQ(f.size(), 9u);
    CHECK_EQ(f.substr(0, 4), std::string("\x00\x00\x00\x05", 4));
    CHECK_EQ(f.substr(4), "hello");
}

TEST("framing: round trip one frame") {
    FrameDecoder d;
    const std::string f = encode_frame("{\"a\":1}");
    d.feed(f.data(), f.size());
    auto p = d.next();
    CHECK(p.has_value());
    CHECK_EQ(*p, "{\"a\":1}");
    CHECK(!d.next().has_value());
    CHECK_EQ(d.buffered(), 0u);
}

TEST("framing: frame split byte by byte across recv calls") {
    FrameDecoder d;
    const std::string f = encode_frame("partial-delivery");
    for (std::size_t i = 0; i + 1 < f.size(); ++i) {
        d.feed(&f[i], 1);
        CHECK(!d.next().has_value());
    }
    d.feed(&f.back(), 1);
    auto p = d.next();
    CHECK(p.has_value() && *p == "partial-delivery");
}

TEST("framing: several frames in one recv") {
    FrameDecoder d;
    const std::string f = encode_frame("one") + encode_frame("two") + encode_frame("three").substr(0, 6);
    d.feed(f.data(), f.size());
    CHECK_EQ(*d.next(), "one");
    CHECK_EQ(*d.next(), "two");
    CHECK(!d.next().has_value());  // third is incomplete
    const std::string rest = encode_frame("three").substr(6);
    d.feed(rest.data(), rest.size());
    CHECK_EQ(*d.next(), "three");
}

TEST("framing: zero length is BAD_FRAME and poisons the decoder") {
    FrameDecoder d;
    const char z[4] = {0, 0, 0, 0};
    d.feed(z, 4);
    CHECK(!d.next().has_value());
    CHECK(d.error() == FrameError::Empty);
    const std::string f = encode_frame("ignored");
    d.feed(f.data(), f.size());
    CHECK(!d.next().has_value());
}

TEST("framing: length above 64 KiB is FRAME_TOO_LARGE before the body arrives") {
    FrameDecoder d;
    const unsigned char h[4] = {0x00, 0x01, 0x00, 0x01};  // 65537
    d.feed(reinterpret_cast<const char*>(h), 4);
    CHECK(!d.next().has_value());
    CHECK(d.error() == FrameError::TooLarge);
}

TEST("framing: exactly 64 KiB is accepted") {
    FrameDecoder d;
    const std::string body(nda::kMaxFrame, 'x');
    const std::string f = encode_frame(body);
    d.feed(f.data(), f.size());
    auto p = d.next();
    CHECK(p.has_value() && p->size() == nda::kMaxFrame);
}

TEST("framing: long-lived stream does not grow the buffer without bound") {
    FrameDecoder d;
    const std::string f = encode_frame(std::string(1000, 'y'));
    for (int i = 0; i < 10000; ++i) {
        d.feed(f.data(), 500);
        d.feed(f.data() + 500, f.size() - 500);
        CHECK(d.next().has_value());
    }
    CHECK_EQ(d.buffered(), 0u);
}

TEST("udp: datagram validation") {
    std::string ok = "NDA1" + std::string(12, '\0');
    CHECK(nda::valid_bench_datagram(ok.data(), ok.size()));
    CHECK(!nda::valid_bench_datagram(ok.data(), 15));
    std::string bad = ok;
    bad[3] = '2';
    CHECK(!nda::valid_bench_datagram(bad.data(), bad.size()));
    std::string big = "NDA1" + std::string(1469, 'p');  // 1473 bytes
    CHECK(!nda::valid_bench_datagram(big.data(), big.size()));
    CHECK(nda::valid_bench_datagram(big.data(), 1472));
}
