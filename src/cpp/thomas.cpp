#include "thomas.hpp"

#include <cmath>

namespace triage {

std::vector<double> thomas(
    const std::vector<double>& lower,
    const std::vector<double>& diag,
    const std::vector<double>& upper,
    const std::vector<double>& rhs) {
  const std::size_t n = diag.size();
  if (n == 0) return {};
  if (n == 1) return {rhs[0] / diag[0]};

  std::vector<double> c(n, 0.0), d(n, 0.0), x(n, 0.0);
  c[0] = upper[0] / diag[0];
  d[0] = rhs[0] / diag[0];
  for (std::size_t i = 1; i < n; ++i) {
    double denom = diag[i] - lower[i] * c[i - 1];
    if (std::abs(denom) < 1e-30) denom = (denom >= 0.0) ? 1e-30 : -1e-30;
    c[i] = (i + 1 < n) ? upper[i] / denom : 0.0;
    d[i] = (rhs[i] - lower[i] * d[i - 1]) / denom;
  }
  x[n - 1] = d[n - 1];
  for (std::size_t i = n - 1; i-- > 0;) {
    x[i] = d[i] - c[i] * x[i + 1];
  }
  return x;
}

}  // namespace triage
