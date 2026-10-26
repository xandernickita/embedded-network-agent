// Minimal test harness: no external dependency, so the tests build offline on the Pi.
#pragma once

#include <cstdio>
#include <functional>
#include <string>
#include <vector>

namespace check {

struct Case {
    const char* name;
    std::function<void()> fn;
};

inline std::vector<Case>& registry() {
    static std::vector<Case> r;
    return r;
}
inline int& failures() {
    static int f = 0;
    return f;
}

struct Register {
    Register(const char* n, std::function<void()> f) { registry().push_back({n, std::move(f)}); }
};

}  // namespace check

#define CHECK_CAT2(a, b) a##b
#define CHECK_CAT(a, b) CHECK_CAT2(a, b)
#define TEST(name)                                                                   \
    static void CHECK_CAT(test_fn_, __LINE__)();                                     \
    static check::Register CHECK_CAT(test_reg_, __LINE__)(name, CHECK_CAT(test_fn_, __LINE__)); \
    static void CHECK_CAT(test_fn_, __LINE__)()

#define CHECK(cond)                                                                          \
    do {                                                                                     \
        if (!(cond)) {                                                                       \
            ++check::failures();                                                             \
            std::fprintf(stderr, "  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);           \
        }                                                                                    \
    } while (0)

#define CHECK_EQ(a, b)                                                                                \
    do {                                                                                              \
        if (!((a) == (b))) {                                                                          \
            ++check::failures();                                                                      \
            std::fprintf(stderr, "  FAIL %s:%d: %s == %s\n", __FILE__, __LINE__, #a, #b);             \
        }                                                                                             \
    } while (0)
