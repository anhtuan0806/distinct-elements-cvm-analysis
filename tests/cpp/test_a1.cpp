#include "cvm/a1.hpp"
#include "cvm/csv_output.hpp"

#include <cstddef>
#include <cstdint>
#include <exception>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <utility>
#include <vector>

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

template <typename Exception, typename Function>
void require_throws(Function function, const char* message) {
    try {
        function();
    } catch (const Exception&) {
        return;
    }
    throw std::runtime_error(message);
}

void require_estimate(const cvm::A1& estimator, double expected) {
    const auto result = estimator.result();
    require(result.status == cvm::A1Status::success, "expected success");
    require(result.estimate.has_value(), "success must have an estimate");
    require(*result.estimate == expected, "unexpected estimate");
}

// A scripted entry represents one coin, not one thinning pass. Unexpected
// probabilities, missing coins, and extra coins all fail the test.
struct ScriptedRandom {
    std::vector<std::pair<double, bool>> coins;
    std::size_t cursor = 0;

    void append(double probability, bool decision, std::size_t count) {
        coins.insert(coins.end(), count, {probability, decision});
    }

    bool operator()(double probability) {
        require(cursor < coins.size(), "unexpected extra random decision");
        const auto coin = coins[cursor++];
        require(probability == coin.first, "unexpected coin probability");
        return coin.second;
    }

    void require_consumed() const {
        require(cursor == coins.size(), "some scripted random decisions were skipped");
    }
};

constexpr std::uint64_t test_m = 256;
constexpr double test_epsilon = 0.9;
constexpr double test_delta = 0.9;
constexpr std::size_t paper_threshold = 166;

void feed_to_threshold(cvm::A1& estimator) {
    require(estimator.threshold() == paper_threshold, "paper threshold must be 166");
    for (std::size_t id = 0; id + 1 < paper_threshold; ++id) {
        estimator.update(static_cast<std::uint64_t>(id));
    }
    require(estimator.sample_size() == paper_threshold - 1, "premature sample change");
    require(estimator.max_buffer_size() == paper_threshold - 1, "incorrect peak before thinning");
    require(estimator.halving_count() == 0, "counted a halving before reaching threshold");
    require(estimator.sampling_probability() == 1.0, "thinned before reaching threshold");
    estimator.update(static_cast<std::uint64_t>(paper_threshold - 1));
}

void duplicates_are_exact_without_thinning() {
    const std::vector<std::uint64_t> input = {
        0, 0, 7, 7, 7, std::numeric_limits<std::uint64_t>::max(), 0, 7};
    ScriptedRandom random;
    cvm::A1 estimator(static_cast<std::uint64_t>(input.size()), 0.5, 0.1, 42,
                      [&random](double p) { return random(p); });
    for (const auto id : input) {
        estimator.update(id);
    }
    require(estimator.processed() == input.size(), "duplicates must count towards m");
    require(estimator.sampling_probability() == 1.0, "small stream should not thin");
    require(estimator.max_buffer_size() == 3, "peak must count distinct sampled IDs");
    require(estimator.halving_count() == 0, "small stream should have no halvings");
    require_estimate(estimator, 3.0);
    random.require_consumed();
}

void repeated_id_is_removed_before_resampling() {
    ScriptedRandom random;
    random.append(0.5, false, paper_threshold - 1);  // Keep all but one in thinning.
    random.append(0.5, true, 1);                    // Discard one element.
    random.append(0.5, false, static_cast<std::size_t>(test_m) - paper_threshold);
    cvm::A1 estimator(test_m, test_epsilon, test_delta, 42,
                      [&random](double p) { return random(p); });
    feed_to_threshold(estimator);
    require(estimator.sample_size() == paper_threshold - 1, "expected one discard");
    require(estimator.sampling_probability() == 0.5, "expected reduced probability");

    std::uint64_t retained_id = 0;
    while (retained_id < paper_threshold && !estimator.contains(retained_id)) {
        ++retained_id;
    }
    require(retained_id < paper_threshold, "expected a retained ID");
    estimator.update(retained_id);  // Script rejects this fresh inclusion coin.
    require(!estimator.contains(retained_id), "old occurrence survived rejected resampling");
    require(estimator.sample_size() == paper_threshold - 2, "duplicate was not removed");
    while (estimator.processed() < test_m) {
        estimator.update(retained_id);
    }
    require_estimate(estimator, 2.0 * static_cast<double>(paper_threshold - 2));
    random.require_consumed();
}

void thinning_halves_probability_and_scales_result() {
    ScriptedRandom random;
    random.append(0.5, true, paper_threshold - 1);  // Discard all but one.
    random.append(0.5, false, 1);                  // Keep one.
    random.append(0.5, false, static_cast<std::size_t>(test_m) - paper_threshold);
    cvm::A1 estimator(test_m, test_epsilon, test_delta, 42,
                      [&random](double p) { return random(p); });
    feed_to_threshold(estimator);
    require(estimator.sample_size() == 1, "expected exactly one retained element");
    require(estimator.max_buffer_size() == paper_threshold,
            "peak must include the full buffer BEFORE successful thinning");
    require(estimator.halving_count() == 1, "successful thinning must count one halving");
    require(estimator.sampling_probability() == 0.5, "p must halve exactly once");
    require(!estimator.aborted(), "successful thinning must not abort");
    while (estimator.processed() < test_m) {
        estimator.update(std::numeric_limits<std::uint64_t>::max());
    }
    require_estimate(estimator, 2.0);  // One sample divided by the NEW p = 1/2.
    require(estimator.max_buffer_size() == paper_threshold, "peak must survive later rejections");
    require(estimator.halving_count() == 1, "rejected insertions must not count as halvings");
    random.require_consumed();
}

void retaining_every_element_aborts_without_retry() {
    ScriptedRandom random;
    random.append(0.5, false, paper_threshold);  // Every discard coin fails.
    cvm::A1 estimator(test_m, test_epsilon, test_delta, 42,
                      [&random](double p) { return random(p); });
    feed_to_threshold(estimator);
    require(estimator.aborted(), "full sample after one thinning pass must abort");
    require(estimator.sample_size() == paper_threshold, "abort sample should remain full");
    require(estimator.max_buffer_size() == paper_threshold, "abort must record the full buffer");
    require(estimator.halving_count() == 1, "the aborting halving must be counted");
    require(estimator.sampling_probability() == 0.5, "p must halve even on abort");
    require(estimator.processed() == paper_threshold, "abort should stop early");
    const auto result = estimator.result();
    require(result.status == cvm::A1Status::aborted, "expected algorithmic abort status");
    require(!result.estimate.has_value(), "abort must not contain a numeric estimate");
    std::ostringstream csv_v2;
    cvm::write_a1_csv(csv_v2, estimator, result, 1.25, cvm::OutputFormat::csv_v2);
    require(csv_v2.str() == "algorithm_abort,,1.25,166,1,166\n",
            "csv-v2 abort must have six columns and an EMPTY estimate");
    std::ostringstream legacy;
    cvm::write_a1_csv(legacy, estimator, result, 1.25, cvm::OutputFormat::legacy_csv);
    require(legacy.str() == "0,TRUE,166,1\n", "legacy abort must keep the zero placeholder");
    require_throws<std::logic_error>([&estimator] { estimator.update(999); },
                                     "update after abort should be rejected");
    require(estimator.processed() == paper_threshold, "update changed aborted state");
    require(estimator.max_buffer_size() == paper_threshold && estimator.halving_count() == 1,
            "rejected update must not change abort metrics");
    require(estimator.result().status == cvm::A1Status::aborted, "abort must persist");
    random.require_consumed();
}

void metrics_accumulate_across_multiple_halvings() {
    ScriptedRandom random;
    random.append(0.5, false, paper_threshold - 1);
    random.append(0.5, true, 1);
    random.append(0.5, true, 1);
    random.append(0.5, true, paper_threshold);
    random.append(0.25, false, static_cast<std::size_t>(test_m) - paper_threshold - 1);
    cvm::A1 estimator(test_m, test_epsilon, test_delta, 42,
                      [&random](double p) { return random(p); });
    feed_to_threshold(estimator);
    estimator.update(static_cast<std::uint64_t>(paper_threshold));
    require(estimator.sample_size() == 0, "second thinning should empty the sample");
    require(estimator.sampling_probability() == 0.25, "two halvings must leave p = 1/4");
    require(estimator.max_buffer_size() == paper_threshold, "peak must precede both thinnings");
    require(estimator.halving_count() == 2, "halving count must accumulate, not act as a flag");
    while (estimator.processed() < test_m) {
        estimator.update(std::numeric_limits<std::uint64_t>::max());
    }
    require_estimate(estimator, 0.0);
    random.require_consumed();
}

void same_seed_reproduces_the_streaming_state() {
    constexpr std::uint64_t m = 4096;
    cvm::A1 first(m, test_epsilon, test_delta, 2026);
    cvm::A1 second(m, test_epsilon, test_delta, 2026);
    for (std::uint64_t i = 0; i < m; ++i) {
        const auto id = i < 2048 ? i : (i * 37) % 2048;
        first.update(id);
        second.update(id);
        require(first.aborted() == second.aborted(), "same seed gave different abort states");
        require(first.sampling_probability() == second.sampling_probability(),
                "same seed gave different sampling probabilities");
        require(first.sample_size() == second.sample_size(), "same seed gave different sizes");
        require(first.max_buffer_size() == second.max_buffer_size(), "same seed gave different peaks");
        require(first.halving_count() == second.halving_count(), "same seed gave different halving counts");
        require(first.threshold() == second.threshold(), "same parameters gave different thresholds");
        if (first.aborted()) {
            break;
        }
    }
    require(first.sampling_probability() < 1.0, "seed test must exercise randomness");
    for (std::uint64_t id = 0; id < 2048; ++id) {
        require(first.contains(id) == second.contains(id), "same seed gave different samples");
    }
    const auto first_result = first.result();
    const auto second_result = second.result();
    require(first_result.status == second_result.status, "same seed gave different results");
    require(first_result.estimate == second_result.estimate, "same seed gave different estimates");
}

void empty_stream_returns_zero() {
    cvm::A1 estimator(0, 0.5, 0.1, 42);
    require(estimator.threshold() == 0, "empty stream must skip the threshold logarithm");
    require(estimator.processed() == 0, "empty stream processed an element");
    require(estimator.max_buffer_size() == 0 && estimator.halving_count() == 0,
            "empty stream must have zero metrics");
    require_estimate(estimator, 0.0);
    require_throws<std::length_error>([&estimator] { estimator.update(0); },
                                      "empty stream must reject updates");
}

void invalid_parameters_are_distinct_from_abort() {
    const std::vector<double> invalid = {
        0.0, -0.1, 1.0, 1.1, std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(), std::numeric_limits<double>::quiet_NaN()};
    for (const auto value : invalid) {
        require_throws<std::invalid_argument>([value] { cvm::A1 estimator(1, value, 0.1, 42); },
                                              "invalid epsilon must throw invalid_argument");
        require_throws<std::invalid_argument>([value] { cvm::A1 estimator(1, 0.5, value, 42); },
                                              "invalid delta must throw invalid_argument");
    }
    require_throws<std::invalid_argument>([] { cvm::A1 estimator(0, 0.0, 0.1, 42); },
                                          "empty stream must still validate parameters");
}

void unrepresentable_threshold_is_rejected() {
    require_throws<std::overflow_error>([] { cvm::A1 estimator(256, 1e-12, 0.9, 42); },
                                        "threshold exceeding size_t must be rejected");
    require_throws<std::overflow_error>(
        [] { cvm::A1 estimator(256, std::numeric_limits<double>::denorm_min(), 0.9, 42); },
        "non-finite threshold must be rejected before integer conversion");
}

void extreme_valid_inputs_do_not_overflow_the_logarithm() {
    const auto m = std::numeric_limits<std::uint64_t>::max();
    cvm::A1 estimator(m, 0.9, std::numeric_limits<double>::denorm_min(), 42);
    require(estimator.threshold() > paper_threshold, "expected finite, larger threshold");
    require(estimator.processed() == 0, "constructor must not consume the stream");
}

void stream_length_is_enforced() {
    cvm::A1 estimator(2, 0.5, 0.1, 42);
    require_throws<std::logic_error>([&estimator] { (void)estimator.result(); },
                                     "unfinished stream must not return success");
    estimator.update(7);
    require_throws<std::logic_error>([&estimator] { (void)estimator.result(); },
                                     "m must count updates, not distinct IDs");
    estimator.update(7);
    require_estimate(estimator, 1.0);
    require_throws<std::length_error>([&estimator] { estimator.update(8); },
                                      "extra update must be rejected");
    require(estimator.processed() == 2 && !estimator.contains(8),
            "rejected update must not change state");
    require_estimate(estimator, 1.0);
}

void all_duplicate_stream_is_exact() {
    ScriptedRandom random;
    cvm::A1 estimator(1024, 0.9, 0.9, 42, [&random](double p) { return random(p); });
    for (std::uint64_t i = 0; i < 1024; ++i) {
        estimator.update(17);
    }
    require_estimate(estimator, 1.0);
    require(estimator.max_buffer_size() == 1 && estimator.halving_count() == 0,
            "all-duplicate stream must retain one ID without thinning");
    random.require_consumed();
}

void all_distinct_stream_is_exact_below_threshold() {
    ScriptedRandom random;
    cvm::A1 estimator(64, 0.9, 0.9, 42, [&random](double p) { return random(p); });
    for (std::uint64_t id = 0; id < 64; ++id) {
        estimator.update(id);
    }
    require_estimate(estimator, 64.0);
    require(estimator.max_buffer_size() == 64 && estimator.halving_count() == 0,
            "all-distinct stream below threshold must keep every ID");
    random.require_consumed();
}

void repeating_stream_counts_distinct_ids() {
    ScriptedRandom random;
    cvm::A1 estimator(512, 0.9, 0.9, 42, [&random](double p) { return random(p); });
    for (std::uint64_t i = 0; i < 512; ++i) {
        estimator.update(i % 8);
    }
    require_estimate(estimator, 8.0);
    require(estimator.processed() == 512 && estimator.max_buffer_size() == 8 &&
                estimator.halving_count() == 0,
            "repeating stream must count all updates but keep only eight IDs");
    random.require_consumed();
}

}  // namespace

int main() {
    const std::vector<std::pair<const char*, void (*)()>> tests = {
        {"duplicates_are_exact_without_thinning", duplicates_are_exact_without_thinning},
        {"repeated_id_is_removed_before_resampling", repeated_id_is_removed_before_resampling},
        {"thinning_halves_probability_and_scales_result", thinning_halves_probability_and_scales_result},
        {"retaining_every_element_aborts_without_retry", retaining_every_element_aborts_without_retry},
        {"metrics_accumulate_across_multiple_halvings", metrics_accumulate_across_multiple_halvings},
        {"same_seed_reproduces_the_streaming_state", same_seed_reproduces_the_streaming_state},
        {"empty_stream_returns_zero", empty_stream_returns_zero},
        {"invalid_parameters_are_distinct_from_abort", invalid_parameters_are_distinct_from_abort},
        {"unrepresentable_threshold_is_rejected", unrepresentable_threshold_is_rejected},
        {"extreme_valid_inputs_do_not_overflow_the_logarithm",
         extreme_valid_inputs_do_not_overflow_the_logarithm},
        {"stream_length_is_enforced", stream_length_is_enforced},
        {"all_duplicate_stream_is_exact", all_duplicate_stream_is_exact},
        {"all_distinct_stream_is_exact_below_threshold", all_distinct_stream_is_exact_below_threshold},
        {"repeating_stream_counts_distinct_ids", repeating_stream_counts_distinct_ids},
    };
    std::size_t failed = 0;
    for (const auto& test : tests) {
        try {
            test.second();
            std::cout << "PASS " << test.first << '\n';
        } catch (const std::exception& error) {
            ++failed;
            std::cerr << "FAIL " << test.first << ": " << error.what() << '\n';
        }
    }
    std::cout << (tests.size() - failed) << '/' << tests.size() << " tests passed\n";
    return failed == 0 ? 0 : 1;
}
