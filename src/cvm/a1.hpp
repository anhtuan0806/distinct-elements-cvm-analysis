#ifndef CVM_A1_HPP
#define CVM_A1_HPP

#include <cstddef>
#include <cstdint>
#include <functional>
#include <optional>
#include <random>
#include <unordered_set>

namespace cvm {

enum class A1Status { success, aborted };

struct A1Result {
    A1Status status;
    // An algorithmic abort has no estimate; it is not an estimate of zero.
    std::optional<double> estimate;
};

// Algorithm 1, page 2 of https://arxiv.org/pdf/2301.10191v2.
// Stores only the sample, PRNG, and streaming state, not the input stream.
class A1 {
public:
    using Id = std::uint64_t;
    // Optional test seam: return a Bernoulli decision with the supplied probability.
    // Calls must be independent for the paper's guarantee. At probability 1 no
    // random decision is needed. A true decision means insert during update,
    // but discard during thinning. Referenced objects must outlive this estimator.
    using RandomDecision = std::function<bool(double)>;

    // m counts all updates, including duplicates. epsilon and delta must be
    // finite and strictly between 0 and 1, including when m is zero.
    // Invalid parameters throw invalid_argument; an unrepresentable threshold
    // throws overflow_error. An empty stream returns zero by project convention.
    A1(std::uint64_t m, double epsilon, double delta, std::uint64_t seed,
       RandomDecision random_decision = {});

    // Throws logic_error after abort, or length_error if this would exceed m.
    void update(Id id);

    // Available after m updates or immediately after abort. Calling earlier
    // throws logic_error. Numeric range errors throw overflow_error, not abort.
    [[nodiscard]] A1Result result() const;

    [[nodiscard]] std::uint64_t processed() const noexcept { return processed_; }
    [[nodiscard]] std::size_t threshold() const noexcept { return threshold_; }
    [[nodiscard]] std::size_t sample_size() const noexcept { return sample_.size(); }
    // Peak size immediately after insertion, BEFORE thinning.
    [[nodiscard]] std::size_t max_buffer_size() const noexcept { return max_buffer_size_; }
    // Counts every p /= 2, including the pass that causes an algorithmic abort.
    [[nodiscard]] std::uint64_t halving_count() const noexcept { return halving_count_; }
    [[nodiscard]] double sampling_probability() const noexcept { return p_; }
    [[nodiscard]] bool aborted() const noexcept { return aborted_; }
    [[nodiscard]] bool contains(Id id) const { return sample_.find(id) != sample_.end(); }

private:
    bool decide(double probability);

    std::uint64_t m_;
    std::uint64_t processed_ = 0;
    std::size_t threshold_;
    std::size_t max_buffer_size_ = 0;
    std::uint64_t halving_count_ = 0;
    double p_ = 1.0;
    bool aborted_ = false;
    std::unordered_set<Id> sample_;
    std::mt19937_64 engine_;
    RandomDecision random_decision_;
};

}  // namespace cvm

#endif  // CVM_A1_HPP
