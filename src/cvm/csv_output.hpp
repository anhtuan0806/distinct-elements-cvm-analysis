#ifndef CVM_CSV_OUTPUT_HPP
#define CVM_CSV_OUTPUT_HPP

#include "cvm/a1.hpp"

#include <iomanip>
#include <limits>
#include <locale>
#include <ostream>
#include <stdexcept>

namespace cvm {

enum class OutputFormat { legacy_csv, csv_v2 };

inline void write_a1_csv(std::ostream& output, const A1& estimator, const A1Result& result,
                         double algorithm_runtime_ms, OutputFormat format) {
    const bool aborted = result.status == A1Status::aborted;
    output.imbue(std::locale::classic());
    output << std::setprecision(std::numeric_limits<double>::max_digits10);
    if (format == OutputFormat::csv_v2) {
        output << (aborted ? "algorithm_abort" : "success") << ',';
        if (!aborted) {
            output << result.estimate.value();
        }
        output << ',' << algorithm_runtime_ms << ',' << estimator.max_buffer_size() << ','
               << estimator.halving_count() << ',' << estimator.threshold() << '\n';
    } else {
        if (!aborted) {
            output << result.estimate.value();
        }
        output << ',' << (aborted ? "TRUE" : "FALSE") << ','
               << estimator.max_buffer_size() << ',' << estimator.halving_count() << '\n';
    }
    if (!output) {
        throw std::runtime_error("failed to write CSV to stdout");
    }
}

}  // namespace cvm

#endif
