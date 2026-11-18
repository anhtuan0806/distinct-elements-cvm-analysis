#include "cvm/a1.hpp"
#include "cvm/csv_output.hpp"

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string_view>

int main(int argc, char* argv[]) {
    // Match the real adapter's invocation for this one controlled configuration.
    constexpr std::array<std::string_view, 10> args = {
        "--m", "256", "--eps", "0.9", "--delta", "0.9", "--seed", "42", "--output-format", "csv-v2"};
    if (argc != static_cast<int>(args.size()) + 1) {
        std::cerr << "abort fixture: unexpected argument count\n";
        return 1;
    }
    for (std::size_t i = 0; i < args.size(); ++i) {
        if (args[i] != argv[i + 1] &&
            !(i == args.size() - 1 && std::string_view(argv[i + 1]) == "threshold-v1")) {
            std::cerr << "abort fixture: unexpected argument " << argv[i + 1] << '\n';
            return 1;
        }
    }
    if (std::string_view(argv[10]) == "threshold-v1") {
        const cvm::A1 estimator(256, 0.9, 0.9, 42);
        std::cout << "threshold-v1," << estimator.threshold() << '\n';
        return 0;
    }

    // Buffer fixture input before timing A1. The injected decisions keep every
    // item at the first halving, so the real algorithm reaches its abort branch.
    std::array<std::uint64_t, 256> ids{};
    for (auto& id : ids) {
        if (!(std::cin >> id)) {
            std::cerr << "abort fixture: missing or invalid ID\n";
            return 1;
        }
    }
    const auto start = std::chrono::steady_clock::now();
    cvm::A1 estimator(ids.size(), 0.9, 0.9, 42, [](double) { return false; });
    for (const auto id : ids) {
        estimator.update(id);
        if (estimator.aborted()) {
            break;
        }
    }
    const auto result = estimator.result();
    const auto elapsed = std::chrono::steady_clock::now() - start;
    cvm::write_a1_csv(std::cout, estimator, result,
                      std::chrono::duration<double, std::milli>(elapsed).count(),
                      cvm::OutputFormat::csv_v2);
}
