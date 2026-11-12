// TV3 measurement hook. The core's stdout and Algorithm 1 are unchanged.
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <psapi.h>
#endif

namespace {

unsigned long long peak_resident_bytes() {
#ifdef _WIN32
    PROCESS_MEMORY_COUNTERS counters{};
    counters.cb = static_cast<DWORD>(sizeof(counters));
    if (K32GetProcessMemoryInfo(GetCurrentProcess(), &counters, counters.cb)) {
        return counters.PeakWorkingSetSize;
    }
#elif defined(__linux__)
    // VmHWM belongs to the current address space after exec, unlike wait4's
    // accounting, which can inherit the peak of the Python parent at fork.
    if (auto* status = std::fopen("/proc/self/status", "r")) {
        unsigned long long peak_kib = 0;
        char line[256];
        while (std::fgets(line, sizeof(line), status)) {
            if (std::sscanf(line, "VmHWM: %llu", &peak_kib) == 1) {
                break;
            }
        }
        std::fclose(status);
        return peak_kib * 1024;
    }
#endif
    return 0;
}

struct PeakResidentReporter {
    ~PeakResidentReporter() {
#ifdef _WIN32
        wchar_t enabled[2]{};
        if (GetEnvironmentVariableW(L"CVM_TV3_PEAK_RSS", enabled, 2) != 1 ||
            enabled[0] != L'1') {
            return;
        }
#else
        const char* enabled = std::getenv("CVM_TV3_PEAK_RSS");
        if (!enabled || std::strcmp(enabled, "1") != 0) {
            return;
        }
#endif
        if (const auto bytes = peak_resident_bytes()) {
            std::fprintf(stderr, "cvm-tv3-peak-rss-v1:%llu\n", bytes);
        }
    }
};

const PeakResidentReporter reporter;

}  // namespace
