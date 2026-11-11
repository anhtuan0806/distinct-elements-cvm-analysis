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
    std::optional<double> estimate;
};


class A1 {
public:
    using Id = std::uint64_t;
  
    using RandomDecision = std::function<bool(double)>;

    A1(std::uint64_t m, double epsilon, double delta, std::uint64_t seed,
       RandomDecision random_decision = {});

 
    void update(Id id);

    [[nodiscard]] A1Result result() const;

    [[nodiscard]] std::uint64_t processed() const noexcept { return processed_; }
    [[nodiscard]] std::size_t threshold() const noexcept { return threshold_; }
    [[nodiscard]] std::size_t sample_size() const noexcept { return sample_.size(); }
    [[nodiscard]] std::size_t max_buffer_size() const noexcept { return max_buffer_size_; }
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

}  

#endif  
