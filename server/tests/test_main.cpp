#include "check.hpp"

int main() {
    int failed_cases = 0;
    for (const auto& c : check::registry()) {
        const int before = check::failures();
        c.fn();
        const bool ok = check::failures() == before;
        if (!ok) ++failed_cases;
        std::printf("%s  %s\n", ok ? "ok  " : "FAIL", c.name);
    }
    std::printf("\n%zu tests, %d failed\n", check::registry().size(), failed_cases);
    return failed_cases == 0 ? 0 : 1;
}
