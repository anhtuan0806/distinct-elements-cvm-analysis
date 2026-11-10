#include "cvm/a1.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

namespace cvm {
namespace {

std::size_t compute_threshold(std::uint64_t m, double epsilon, double delta) {
    if (!std::isfinite(epsilon) || epsilon <= 0.0 || epsilon >= 1.0) {
        throw std::invalid_argument("epsilon must be finite and in (0, 1)");
    }
    if (!std::isfinite(delta) || delta <= 0.0 || delta >= 1.0) {
        throw std::invalid_argument("delta must be finite and in (0, 1)");
    }
    if (m == 0) {
        return 0;  
    }

 
    const auto eps = static_cast<long double>(epsilon);
    const auto log_term = 3.0L + std::log2(static_cast<long double>(m)) -
                          std::log2(static_cast<long double>(delta));
    const auto rounded = std::ceil((12.0L / eps / eps) * log_term);


    const auto upper_bound = std::ldexp(1.0L, std::numeric_limits<std::size_t>::digits);
    if (!std::isfinite(rounded) || rounded < 1.0L || rounded >= upper_bound) {
        throw std::overflow_error("A1 threshold does not fit in size_t");
    }
    return static_cast<std::size_t>(rounded);
}

}  // namespace

A1::A1(std::uint64_t m, double epsilon, double delta, std::uint64_t seed,
       RandomDecision random_decision)
    : m_(m),
      threshold_(compute_threshold(m, epsilon, delta)),
      engine_(seed),
      random_decision_(std::move(random_decision)) {
    if (threshold_ > sample_.max_size()) {
        throw std::overflow_error("A1 threshold exceeds the sample container's capacity");
    }
}

bool A1::decide(double probability) {
    if (probability == 1.0) {
        return true;
    }
    if (random_decision_) {
        return random_decision_(probability);
    }
    return std::bernoulli_distribution(probability)(engine_);
}

void A1::update(Id id) {
    if (aborted_) {
        throw std::logic_error("cannot update an aborted A1 estimator");
    }
    if (processed_ == m_) {
        throw std::length_error("update would exceed the declared stream length m");
    }

    ++processed_;
    sample_.erase(id);
    if (decide(p_)) {
        sample_.insert(id);
        max_buffer_size_ = std::max(max_buffer_size_, sample_.size());
    }

    if (sample_.size() == threshold_) {
        const double next_p = p_ / 2.0;
        if (next_p == 0.0) {
            throw std::overflow_error("A1 sampling probability would underflow");
        }
        for (auto it = sample_.begin(); it != sample_.end();) {
            if (decide(0.5)) {
                it = sample_.erase(it);
            } else {
                ++it;
            }
        }
        p_ = next_p;
        ++halving_count_;
        if (sample_.size() == threshold_) {
            aborted_ = true;
        }
    }
}

A1Result A1::result() const {
    if (aborted_) {
        return {A1Status::aborted, std::nullopt};
    }
    if (processed_ != m_) {
        throw std::logic_error("A1 result requires exactly m updates unless aborted");
    }
    const double estimate = static_cast<double>(sample_.size()) / p_;
    if (!std::isfinite(estimate)) {
        throw std::overflow_error("A1 estimate does not fit in double");
    }
    return {A1Status::success, estimate};
}

}  // namespace cvm
