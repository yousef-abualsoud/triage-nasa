#pragma once

#include <vector>

namespace triage {

// Solve a tridiagonal system A x = rhs. lower[0] and upper[n-1] are ignored.
std::vector<double> thomas(
    const std::vector<double>& lower,
    const std::vector<double>& diag,
    const std::vector<double>& upper,
    const std::vector<double>& rhs);

}  // namespace triage
