#include "cvm/a1.hpp"

#include <charconv>
#include <cstdint>
#include <exception>
#include <iomanip>
#include <iostream>
#include <limits>
#include <locale>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>

namespace {

struct Options {
    std::optional<std::uint64_t> m;
    std::optional<double> epsilon;
    std::optional<double> delta;
    std::optional<std::uint64_t> seed;
};

template <typename Number>
Number parse_number(std::string_view text, const std::string& label) {
    Number value{};
    if (!text.empty()) {
        const auto end = text.data() + text.size();
        const auto parsed = std::from_chars(text.data(), end, value);
        if (parsed.ec == std::errc{} && parsed.ptr == end) {
            return value;
        }
    }
    throw std::invalid_argument("invalid " + label + ": expected a decimal number in range");
}

template <typename Number>
void set_option(std::optional<Number>& option, std::string_view text, const std::string& name) {
    if (option.has_value()) {
        throw std::invalid_argument("duplicate argument " + name);
    }
    option = parse_number<Number>(text, name);
}

Options parse_options(int argc, char* argv[]) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string name = argv[i];
        if (name != "--m" && name != "--eps" && name != "--delta" && name != "--seed") {
            throw std::invalid_argument("unknown argument " + name);
        }
        if (i + 1 == argc) {
            throw std::invalid_argument("missing value for " + name);
        }
        const std::string_view value = argv[++i];
        if (name == "--m") {
            set_option(options.m, value, name);
        } else if (name == "--eps") {
            set_option(options.epsilon, value, name);
        } else if (name == "--delta") {
            set_option(options.delta, value, name);
        } else {
            set_option(options.seed, value, name);
        }
    }
    if (!options.m.has_value()) {
        throw std::invalid_argument("missing required argument --m");
    }
    if (!options.epsilon.has_value()) {
        throw std::invalid_argument("missing required argument --eps");
    }
    if (!options.delta.has_value()) {
        throw std::invalid_argument("missing required argument --delta");
    }
    if (!options.seed.has_value()) {
        throw std::invalid_argument("missing required argument --seed");
    }
    return options;
}

std::string_view trim_id(std::string_view line) {
    constexpr std::string_view whitespace = " \t\r\v\f";
    const auto first = line.find_first_not_of(whitespace);
    if (first == std::string_view::npos) {
        return {};
    }
    const auto last = line.find_last_not_of(whitespace);
    return line.substr(first, last - first + 1);
}

}  // namespace

int main(int argc, char* argv[]) {
    try {
        const auto options = parse_options(argc, argv);
        cvm::A1 estimator(*options.m, *options.epsilon, *options.delta, *options.seed);
        std::string line;
        while (estimator.processed() < *options.m && !estimator.aborted()) {
            if (!std::getline(std::cin, line)) {
                if (std::cin.bad()) {
                    throw std::runtime_error("failed to read stdin");
                }
                throw std::runtime_error("input ended after " + std::to_string(estimator.processed()) +
                                         " IDs; expected " + std::to_string(*options.m));
            }
            const auto label = "uint64 ID at line " + std::to_string(estimator.processed() + 1);
            estimator.update(parse_number<std::uint64_t>(trim_id(line), label));
        }

        const auto result = estimator.result();
        const bool aborted = result.status == cvm::A1Status::aborted;
        // Keep the core's null estimate for abort; only the CSV adapter uses zero.
        const double estimate = aborted ? 0.0 : result.estimate.value();
        std::cout.imbue(std::locale::classic());
        std::cout << std::setprecision(std::numeric_limits<double>::max_digits10)
                  << estimate << ',' << (aborted ? "TRUE" : "FALSE") << ','
                  << estimator.max_buffer_size() << ',' << estimator.halving_count() << '\n';
        if (!std::cout) {
            throw std::runtime_error("failed to write CSV to stdout");
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "cvm_core: " << error.what() << '\n';
        return 1;
    }
}
