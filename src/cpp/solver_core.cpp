#include "solver_core.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <limits>
#include <stdexcept>

#include "thomas.hpp"

namespace triage {
namespace {

constexpr double PI = 3.14159265358979323846;
constexpr int MAX_SUBSTEPS_PER_OUTER = 400;
constexpr int COARSE_RADIAL_POINTS = 64;
constexpr double MAX_DELTA_T_CHEM = 200.0;

double clampd(double x, double lo, double hi) {
  return std::min(std::max(x, lo), hi);
}

double round_to(double x, int decimals) {
  const double scale = std::pow(10.0, static_cast<double>(decimals));
  return std::round(x * scale) / scale;
}

double dot(const std::vector<double>& a, const std::vector<double>& b) {
  double s = 0.0;
  for (std::size_t i = 0; i < a.size(); ++i) s += a[i] * b[i];
  return s;
}

std::vector<double> zeros(std::size_t n) { return std::vector<double>(n, 0.0); }

void normalise_Y(std::vector<double>& Y, int n2_index) {
  double sum = 0.0;
  for (double& v : Y) {
    if (!std::isfinite(v)) v = 0.0;
    v = std::max(v, 0.0);
    sum += v;
  }
  if (sum > 1e-12) {
    for (double& v : Y) v /= sum;
  } else {
    std::fill(Y.begin(), Y.end(), 0.0);
    if (n2_index >= 0 && n2_index < static_cast<int>(Y.size())) Y[n2_index] = 1.0;
  }
}

double gravity_magnitude(const Config& cfg) {
  if (cfg.gravity_mode == "custom") return cfg.custom_gravity_m_per_s2;
  if (cfg.gravity_mode == "iss_micro_g") return 1.0e-6;
  if (cfg.gravity_mode == "earth_1g") return 9.80665;
  if (cfg.gravity_mode == "mars_g") return 3.726;
  if (cfg.gravity_mode == "moon_g") return 1.62;
  return 0.0;
}

}  // namespace

// ---------------------------------------------------------------------------
// Species
// ---------------------------------------------------------------------------

namespace {
const double* therm_coeffs(const Species& s, double T) {
  return (T <= s.t_mid) ? s.nasa_low : s.nasa_high;
}
double h_integral(const Species& s, double T, double R) {
  const double* a = therm_coeffs(s, T);
  return R * (a[0] * T + a[1] * T * T / 2.0 + a[2] * T * T * T / 3.0 +
              a[3] * std::pow(T, 4) / 4.0 + a[4] * std::pow(T, 5) / 5.0 + a[5]);
}
}  // namespace

double Species::cp_mass(double T) const {
  T = std::max(T, 1.0);
  if (has_nasa) {
    const double* a = therm_coeffs(*this, T);
    const double R = 8.314462;
    return R * (a[0] + a[1] * T + a[2] * T * T + a[3] * T * T * T +
                a[4] * std::pow(T, 4)) /
           W;
  }
  return cp_const;
}

double Species::hs_mass(double T) const {
  T = std::max(T, 1.0);
  if (has_nasa) {
    const double R = 8.314462;
    return (h_integral(*this, T, R) - h_integral(*this, 298.15, R)) / W;
  }
  return cp_const * (T - 298.15);
}

double Species::thermal_conductivity(double T) const {
  return k_ref * std::pow(std::max(T, 1.0) / k_t_ref, k_exp);
}

double Species::viscosity(double T) const {
  return mu_ref * std::pow(std::max(T, 1.0) / mu_t_ref, mu_exp);
}

double Species::diffusivity(double T, double pressure_pa) const {
  const double p = std::max(pressure_pa, 1.0);
  return d_ref * std::pow(std::max(T, 1.0) / d_t_ref, d_exp) * (101325.0 / p);
}

// ---------------------------------------------------------------------------
// Mechanism
// ---------------------------------------------------------------------------

double Mechanism::cp_species(int k, double T) const { return species[k].cp_mass(T); }
double Mechanism::hs_species(int k, double T) const { return species[k].hs_mass(T); }

double Mechanism::cp_mix(double T, const std::vector<double>& Y) const {
  double cp = 0.0;
  for (int k = 0; k < size(); ++k) cp += Y[k] * species[k].cp_mass(T);
  return cp;
}

double Mechanism::hs_mix(double T, const std::vector<double>& Y) const {
  double hs = 0.0;
  for (int k = 0; k < size(); ++k) hs += Y[k] * species[k].hs_mass(T);
  return hs;
}

double Mechanism::lambda_mix(double T, const std::vector<double>& Y) const {
  double lambda = 0.0;
  for (int k = 0; k < size(); ++k) lambda += Y[k] * species[k].thermal_conductivity(T);
  return lambda;
}

double Mechanism::molecular_weight(const std::vector<double>& Y) const {
  double inv = 0.0;
  for (int k = 0; k < size(); ++k) inv += Y[k] / W[k];
  return 1.0 / std::max(inv, 1e-30);
}

double Mechanism::density(double T, double p0, const std::vector<double>& Y) const {
  return p0 * molecular_weight(Y) / (r_univ * std::max(T, 1.0));
}

double Mechanism::rate_of_progress(double T, const std::vector<double>& C) const {
  T = std::max(T, 200.0);
  double product = 1.0;
  for (int k = 0; k < size(); ++k) {
    const double order = orders[k];
    if (order > 0.0) product *= std::pow(std::max(C[k], 0.0), order);
  }
  double value = A * std::pow(T, beta) * std::exp(-Ea / (r_univ * T)) * product;
  if (!std::isfinite(value)) value = 1e30;
  return std::min(std::max(value, 0.0), 1e30);
}

double Mechanism::temperature_from_hs(
    double hs_target, const std::vector<double>& Y, double T_guess) const {
  double T = clampd(T_guess, 200.0, 6000.0);
  for (int it = 0; it < 24; ++it) {
    const double f = hs_mix(T, Y) - hs_target;
    const double cp = std::max(cp_mix(T, Y), 1.0);
    const double step = f / cp;
    const double T_new = clampd(T - step, 200.0, 6000.0);
    if (std::abs(T_new - T) < 1e-6) {
      T = T_new;
      break;
    }
    T = T_new;
  }
  return T;
}

// ---------------------------------------------------------------------------
// Grid
// ---------------------------------------------------------------------------

Grid::Grid(double r_min_, double r_max_, int n_) : r_min(r_min_), r_max(r_max_), n(n_) {
  if (n < 1) throw std::invalid_argument("Nr must be >= 1");
  if (r_max <= r_min) throw std::invalid_argument("r_max must be > r_min");
  dr = (r_max - r_min) / n;
  r_faces.resize(n + 1);
  r_centers.resize(n);
  face_area.resize(n + 1);
  cell_volume.resize(n);
  for (int i = 0; i <= n; ++i) {
    r_faces[i] = r_min + i * dr;
    face_area[i] = 4.0 * PI * r_faces[i] * r_faces[i];
  }
  for (int i = 0; i < n; ++i) {
    r_centers[i] = r_min + (i + 0.5) * dr;
    cell_volume[i] = (4.0 * PI / 3.0) *
                     (r_faces[i + 1] * r_faces[i + 1] * r_faces[i + 1] -
                      r_faces[i] * r_faces[i] * r_faces[i]);
  }
}

std::vector<double> Grid::face_average(const std::vector<double>& a) const {
  std::vector<double> out(n + 1);
  out[0] = a[0];
  out[n] = a[n - 1];
  for (int i = 1; i < n; ++i) out[i] = 0.5 * (a[i - 1] + a[i]);
  return out;
}

std::vector<double> Grid::gradient(const std::vector<double>& a) const {
  std::vector<double> out(n, 0.0);
  if (n == 1) return out;
  out[0] = (a[1] - a[0]) / dr;
  out[n - 1] = (a[n - 1] - a[n - 2]) / dr;
  for (int i = 1; i < n - 1; ++i) out[i] = (a[i + 1] - a[i - 1]) / (2.0 * dr);
  return out;
}

std::vector<double> Grid::face_gradient(const std::vector<double>& a) const {
  std::vector<double> out(n + 1);
  for (int i = 1; i < n; ++i) out[i] = (a[i] - a[i - 1]) / dr;
  out[0] = (a[0] - a[1]) / dr;
  out[n] = (a[n - 1] - a[n - 2]) / dr;
  return out;
}

std::vector<double> Grid::divergence(const std::vector<double>& flux) const {
  std::vector<double> out(n);
  for (int i = 0; i < n; ++i) {
    out[i] = (face_area[i + 1] * flux[i + 1] - face_area[i] * flux[i]) / cell_volume[i];
  }
  return out;
}

// ---------------------------------------------------------------------------
// Transport kernels
// ---------------------------------------------------------------------------

namespace {

std::vector<double> implicit_diffusion_1d(
    const std::vector<double>& values,
    const Grid& grid,
    std::vector<double> coef,
    const std::vector<double>& scale,
    double ghost_inner,
    double ghost_outer,
    const std::string& bc_inner,
    const std::string& bc_outer) {
  const int n = grid.n;
  if (bc_inner != "fixed") coef[0] = 0.0;
  if (bc_outer != "fixed") coef[n] = 0.0;

  std::vector<double> lower(n, 0.0), diag(n, 1.0), upper(n, 0.0), rhs = values;
  for (int i = 1; i < n; ++i) lower[i] = -scale[i] * coef[i];
  for (int i = 0; i < n - 1; ++i) upper[i] = -scale[i] * coef[i + 1];
  for (int i = 0; i < n; ++i) diag[i] = 1.0 + scale[i] * (coef[i] + coef[i + 1]);
  if (bc_inner == "fixed") rhs[0] += scale[0] * coef[0] * ghost_inner;
  if (bc_outer == "fixed") rhs[n - 1] += scale[n - 1] * coef[n] * ghost_outer;
  return thomas(lower, diag, upper, rhs);
}

std::vector<std::vector<double>> implicit_diffusion_species(
    const std::vector<std::vector<double>>& Y,
    double dt,
    const Grid& grid,
    const std::vector<double>& rho,
    const std::vector<std::vector<double>>& D_face,
    const std::vector<double>& Y_inner,
    const std::vector<double>& Y_outer,
    const std::string& bc_inner,
    const std::string& bc_outer) {
  const int n = grid.n;
  const int ns = static_cast<int>(Y[0].size());
  const std::vector<double> rho_face = grid.face_average(rho);
  std::vector<std::vector<double>> out(n, std::vector<double>(ns, 0.0));
  for (int k = 0; k < ns; ++k) {
    std::vector<double> coef(n + 1), scale(n);
    for (int i = 0; i <= n; ++i) coef[i] = grid.face_area[i] * rho_face[i] * D_face[i][k] / grid.dr;
    for (int i = 0; i < n; ++i) scale[i] = dt / (std::max(rho[i], 1e-30) * grid.cell_volume[i]);
    std::vector<double> col(n);
    for (int i = 0; i < n; ++i) col[i] = Y[i][k];
    const std::vector<double> solved =
        implicit_diffusion_1d(col, grid, coef, scale, Y_inner[k], Y_outer[k], bc_inner, bc_outer);
    for (int i = 0; i < n; ++i) out[i][k] = solved[i];
  }
  return out;
}

std::vector<double> implicit_diffusion_temperature(
    const std::vector<double>& T,
    double dt,
    const Grid& grid,
    const std::vector<double>& rho,
    const std::vector<double>& cp,
    const std::vector<double>& lambda_face,
    double T_inner,
    double T_outer,
    const std::string& bc_inner,
    const std::string& bc_outer) {
  const int n = grid.n;
  std::vector<double> coef(n + 1), scale(n);
  for (int i = 0; i <= n; ++i) coef[i] = grid.face_area[i] * lambda_face[i] / grid.dr;
  for (int i = 0; i < n; ++i) scale[i] = dt / (std::max(rho[i], 1e-30) * std::max(cp[i], 1.0) * grid.cell_volume[i]);
  return implicit_diffusion_1d(T, grid, coef, scale, T_inner, T_outer, bc_inner, bc_outer);
}

std::vector<double> upwind_advection_1d(
    const std::vector<double>& F,
    const std::vector<double>& u,
    double dt,
    const Grid& grid,
    double ghost_inner,
    double ghost_outer,
    const std::string& bc_inner,
    const std::string& bc_outer) {
  const int n = grid.n;
  std::vector<double> out(n);
  for (int i = 0; i < n; ++i) {
    double left;
    double right;
    if (i == 0) left = (bc_inner == "fixed") ? ghost_inner : F[0];
    else left = F[i - 1];
    if (i == n - 1) right = (bc_outer == "fixed") ? ghost_outer : F[n - 1];
    else right = F[i + 1];
    const double grad = (u[i] >= 0.0) ? (F[i] - left) / grid.dr : (right - F[i]) / grid.dr;
    out[i] = F[i] - dt * u[i] * grad;
  }
  return out;
}

std::vector<std::vector<double>> upwind_advection_species(
    const std::vector<std::vector<double>>& Y,
    const std::vector<double>& u,
    double dt,
    const Grid& grid,
    const std::vector<double>& Y_inner,
    const std::vector<double>& Y_outer,
    const std::string& bc_inner,
    const std::string& bc_outer) {
  const int n = grid.n;
  const int ns = static_cast<int>(Y[0].size());
  std::vector<std::vector<double>> out(n, std::vector<double>(ns, 0.0));
  for (int k = 0; k < ns; ++k) {
    std::vector<double> col(n);
    for (int i = 0; i < n; ++i) col[i] = Y[i][k];
    const std::vector<double> solved =
        upwind_advection_1d(col, u, dt, grid, Y_inner[k], Y_outer[k], bc_inner, bc_outer);
    for (int i = 0; i < n; ++i) out[i][k] = solved[i];
  }
  return out;
}

struct FluxBundle {
  std::vector<std::vector<double>> j_fick;  // [n+1][ns]
  std::vector<std::vector<double>> j_corr;
  std::vector<std::vector<double>> j_total;
  std::vector<double> v_corr;                // [n+1]
  std::vector<std::vector<double>> Y_face;   // [n+1][ns]
};

FluxBundle diffusive_fluxes(
    const std::vector<std::vector<double>>& Y,
    const Grid& grid,
    const std::vector<double>& rho,
    const std::vector<std::vector<double>>& D_face,
    const std::vector<double>& Y_inner,
    const std::vector<double>& Y_outer,
    const std::string& bc_inner,
    const std::string& bc_outer) {
  const int n = grid.n;
  const int ns = static_cast<int>(Y[0].size());
  const std::vector<double> rho_face = grid.face_average(rho);
  FluxBundle b;
  b.j_fick.assign(n + 1, std::vector<double>(ns, 0.0));
  b.j_corr.assign(n + 1, std::vector<double>(ns, 0.0));
  b.j_total.assign(n + 1, std::vector<double>(ns, 0.0));
  b.v_corr.assign(n + 1, 0.0);
  b.Y_face.assign(n + 1, std::vector<double>(ns, 0.0));

  for (int f = 0; f <= n; ++f) {
    for (int k = 0; k < ns; ++k) {
      double grad = 0.0;
      if (f == 0) {
        grad = (bc_inner == "fixed") ? (Y[0][k] - Y_inner[k]) / grid.dr : 0.0;
      } else if (f == n) {
        grad = (bc_outer == "fixed") ? (Y_outer[k] - Y[n - 1][k]) / grid.dr : 0.0;
      } else {
        grad = (Y[f][k] - Y[f - 1][k]) / grid.dr;
      }
      b.j_fick[f][k] = -rho_face[f] * D_face[f][k] * grad;
      b.v_corr[f] += D_face[f][k] * grad;
    }
    for (int k = 0; k < ns; ++k) {
      double yf;
      if (f == 0) yf = (bc_inner == "fixed") ? Y_inner[k] : Y[0][k];
      else if (f == n) yf = (bc_outer == "fixed") ? Y_outer[k] : Y[n - 1][k];
      else yf = 0.5 * (Y[f - 1][k] + Y[f][k]);
      b.Y_face[f][k] = yf;
      b.j_corr[f][k] = rho_face[f] * yf * b.v_corr[f];
      b.j_total[f][k] = b.j_fick[f][k] + b.j_corr[f][k];
    }
  }
  return b;
}

std::vector<std::vector<double>> divergence_species(
    const std::vector<std::vector<double>>& flux, const Grid& grid) {
  const int n = grid.n;
  const int ns = static_cast<int>(flux[0].size());
  std::vector<std::vector<double>> out(n, std::vector<double>(ns, 0.0));
  for (int i = 0; i < n; ++i) {
    for (int k = 0; k < ns; ++k) {
      out[i][k] = (grid.face_area[i + 1] * flux[i + 1][k] -
                   grid.face_area[i] * flux[i][k]) /
                  grid.cell_volume[i];
    }
  }
  return out;
}

std::vector<double> species_enthalpy_flux(
    const Mechanism& mech,
    const std::vector<double>& T,
    const std::vector<std::vector<double>>& j_total,
    const Grid& grid) {
  const int n = grid.n;
  const int ns = mech.size();
  std::vector<double> out(n + 1, 0.0);
  for (int f = 0; f <= n; ++f) {
    double sum = 0.0;
    for (int k = 0; k < ns; ++k) {
      double hs_face;
      if (f == 0) hs_face = mech.hs_species(k, T[0]);
      else if (f == n) hs_face = mech.hs_species(k, T[n - 1]);
      else hs_face = 0.5 * (mech.hs_species(k, T[f - 1]) + mech.hs_species(k, T[f]));
      sum += hs_face * j_total[f][k];
    }
    out[f] = sum;
  }
  return out;
}

void integrate_chemistry(
    const Mechanism& mech,
    std::vector<double>& T,
    std::vector<std::vector<double>>& Y,
    const std::vector<double>& rho,
    double dt,
    Diagnostics& diag) {
  const int n = static_cast<int>(T.size());
  const int ns = mech.size();
  std::vector<double> dxi(n, 0.0), xi_dot(n, 0.0);
  std::vector<std::vector<double>> C(n, std::vector<double>(ns, 0.0));
  std::vector<double> hs_old(n), cp(n);
  for (int i = 0; i < n; ++i) {
    for (int k = 0; k < ns; ++k) C[i][k] = rho[i] * Y[i][k] / mech.W[k];
    xi_dot[i] = mech.rate_of_progress(T[i], C[i]);
    double xi_limit = std::numeric_limits<double>::infinity();
    for (int k = 0; k < ns; ++k) {
      if (mech.nu[k] < 0.0) {
        const double avail = rho[i] * std::max(Y[i][k], 0.0) / (mech.W[k] * (-mech.nu[k]));
        xi_limit = std::min(xi_limit, avail);
      }
    }
    if (!std::isfinite(xi_limit)) xi_limit = 0.0;
    cp[i] = std::max(mech.cp_mix(T[i], Y[i]), 1.0);
    if (mech.heat_of_reaction > 1e-30) {
      const double xi_limit_t = MAX_DELTA_T_CHEM * rho[i] * cp[i] / mech.heat_of_reaction;
      xi_limit = std::min(xi_limit, xi_limit_t);
    }
    dxi[i] = std::min(xi_dot[i] * dt, xi_limit);
    dxi[i] = std::max(dxi[i], 0.0);
  }

  double max_xi_dot = 0.0, max_xi_actual = 0.0, max_qdot = 0.0, reacted = 0.0;
  for (int i = 0; i < n; ++i) {
    max_xi_dot = std::max(max_xi_dot, xi_dot[i]);
    max_xi_actual = std::max(max_xi_actual, dxi[i] / std::max(dt, 1e-30));
    max_qdot = std::max(max_qdot, mech.heat_of_reaction * dxi[i] / std::max(dt, 1e-30));
    reacted += dxi[i];
    if (dxi[i] <= 0.0) continue;
    hs_old[i] = mech.hs_mix(T[i], Y[i]);
    for (int k = 0; k < ns; ++k) {
      Y[i][k] += mech.nu[k] * mech.W[k] * dxi[i] / std::max(rho[i], 1e-30);
    }
    normalise_Y(Y[i], mech.n2_index);
    const double hs_new = hs_old[i] + mech.heat_of_reaction * dxi[i] / std::max(rho[i], 1e-30);
    T[i] = clampd(mech.temperature_from_hs(hs_new, Y[i], T[i]), 200.0, 6000.0);
  }
  diag.chem_xi_dot_max = max_xi_dot;
  diag.chem_xi_actual_max = max_xi_actual;
  diag.chem_heat_release_max = max_qdot;
  diag.chem_reacted_extent = reacted;
}

}  // namespace

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

namespace {

struct Boundaries {
  std::vector<double> Y_inner;
  std::vector<double> Y_outer;
  double T_inner = 300.0;
  double T_outer = 300.0;
};

std::vector<double> oxygen_stream_composition(
    const Mechanism& mech, double oxygen_pct, const std::string& oxidizer) {
  std::vector<double> y(mech.size(), 0.0);
  const int o2 = mech.o2_index;
  const int n2 = mech.n2_index;
  if (o2 < 0) throw std::invalid_argument("mechanism must include O2");
  const double x = (oxidizer == "O2") ? 1.0 : clampd(oxygen_pct / 100.0, 1e-6, 1.0);
  double y_o2 = 1.0;
  if (n2 >= 0) y_o2 = x * mech.W[o2] / (x * mech.W[o2] + (1.0 - x) * mech.W[n2]);
  y[o2] = y_o2;
  if (n2 >= 0) y[n2] = 1.0 - y_o2;
  return y;
}

std::vector<double> premixed_composition(
    const Mechanism& mech,
    double equivalence_ratio,
    double oxygen_pct,
    const std::string& oxidizer) {
  const int fuel = mech.fuel_index;
  const int o2 = mech.o2_index;
  const int n2 = mech.n2_index;
  if (o2 < 0) throw std::invalid_argument("mechanism must include O2");
  const double nu_o2 = -mech.nu[o2];
  if (nu_o2 <= 0.0) throw std::invalid_argument("reaction has no O2 reactant");
  const double phi = std::max(equivalence_ratio, 1e-6);
  const double x = (oxidizer == "O2") ? 1.0 : clampd(oxygen_pct / 100.0, 1e-6, 1.0);
  double y_o2_stream = 1.0;
  if (n2 >= 0) y_o2_stream = x * mech.W[o2] / (x * mech.W[o2] + (1.0 - x) * mech.W[n2]);
  const double y_n2_stream = 1.0 - y_o2_stream;

  const double n_o2 = nu_o2 / phi;
  const double mass_fuel = mech.W[fuel];
  const double mass_o2 = n_o2 * mech.W[o2];
  const double mass_n2 =
      (y_o2_stream > 1e-12) ? mass_o2 * (y_n2_stream / y_o2_stream) : 0.0;
  const double total = mass_fuel + mass_o2 + mass_n2;
  std::vector<double> y(mech.size(), 0.0);
  y[fuel] = mass_fuel / total;
  y[o2] = mass_o2 / total;
  if (n2 >= 0) y[n2] = mass_n2 / total;
  return y;
}

std::vector<double> composition_from_dict(
    const Mechanism& mech, const std::map<std::string, double>& mapping) {
  std::vector<double> y(mech.size(), 0.0);
  double total = 0.0;
  for (const auto& kv : mapping) {
    auto it = std::find(mech.keys.begin(), mech.keys.end(), kv.first);
    if (it != mech.keys.end()) {
      const int idx = static_cast<int>(std::distance(mech.keys.begin(), it));
      y[idx] = std::max(kv.second, 0.0);
      total += y[idx];
    }
  }
  if (total > 1.0 + 1e-9) {
    for (double& v : y) v /= total;
  } else if (mech.n2_index >= 0 && total < 1.0) {
    y[mech.n2_index] += 1.0 - total;
  }
  return y;
}

Boundaries boundary_compositions(const Config& cfg, const Mechanism& mech) {
  Boundaries b;
  b.T_inner = cfg.has_inlet_temperature ? cfg.inlet_temperature_k : cfg.ambient_temperature_k;
  b.T_outer = cfg.ambient_temperature_k;
  if (cfg.mixing_mode == "premixed") {
    const std::vector<double> premixed =
        premixed_composition(mech, cfg.equivalence_ratio, cfg.oxygen_pct, cfg.oxidizer);
    b.Y_inner = cfg.fuel_inlet_composition.empty()
                    ? premixed
                    : composition_from_dict(mech, cfg.fuel_inlet_composition);
    b.Y_outer = cfg.oxidizer_inlet_composition.empty()
                    ? premixed
                    : composition_from_dict(mech, cfg.oxidizer_inlet_composition);
  } else {
    if (!cfg.fuel_inlet_composition.empty()) {
      b.Y_inner = composition_from_dict(mech, cfg.fuel_inlet_composition);
    } else {
      b.Y_inner.assign(mech.size(), 0.0);
      b.Y_inner[mech.fuel_index] = 1.0;
    }
    b.Y_outer = cfg.oxidizer_inlet_composition.empty()
                    ? oxygen_stream_composition(mech, cfg.oxygen_pct, cfg.oxidizer)
                    : composition_from_dict(mech, cfg.oxidizer_inlet_composition);
  }
  return b;
}

std::vector<std::vector<double>> initial_composition(
    const Config& cfg, const Mechanism& mech, const Grid& grid) {
  const int n = grid.n;
  const int ns = mech.size();
  if (!cfg.initial_species_mass_fractions.empty()) {
    const std::vector<double> y0 = composition_from_dict(mech, cfg.initial_species_mass_fractions);
    return std::vector<std::vector<double>>(n, y0);
  }
  if (cfg.mixing_mode == "premixed") {
    const std::vector<double> y0 =
        premixed_composition(mech, cfg.equivalence_ratio, cfg.oxygen_pct, cfg.oxidizer);
    return std::vector<std::vector<double>>(n, y0);
  }
  const Boundaries b = boundary_compositions(cfg, mech);
  const double mid = 0.5 * (grid.r_min + grid.r_max);
  const double delta = std::max(cfg.ignition_region_m * 0.5, 2.0 * grid.dr);
  std::vector<std::vector<double>> Y(n, std::vector<double>(ns, 0.0));
  for (int i = 0; i < n; ++i) {
    const double w = 0.5 * (1.0 + std::tanh((grid.r_centers[i] - mid) / delta));
    for (int k = 0; k < ns; ++k) {
      Y[i][k] = (1.0 - w) * b.Y_inner[k] + w * b.Y_outer[k];
    }
  }
  return Y;
}

double estimate_adiabatic_flame_temp(
    const Mechanism& mech, double t0, const std::vector<double>& Y) {
  const int fuel = mech.fuel_index;
  const int o2 = mech.o2_index;
  if (o2 < 0) return 2500.0;
  const double nu_f = -mech.nu[fuel];
  const double nu_o = -mech.nu[o2];
  if (nu_f <= 0.0 || nu_o <= 0.0) return 2500.0;
  const double dxi = std::min(Y[fuel] / (mech.W[fuel] * nu_f),
                              Y[o2] / (mech.W[o2] * nu_o));
  std::vector<double> y_prod = Y;
  for (int k = 0; k < mech.size(); ++k) {
    y_prod[k] = std::max(y_prod[k] + mech.nu[k] * mech.W[k] * dxi, 0.0);
  }
  normalise_Y(y_prod, mech.n2_index);
  const double h_react = dot(Y, mech.hf_mass) + mech.hs_mix(t0, Y);
  double lo = 200.0, hi = 6000.0;
  for (int it = 0; it < 80; ++it) {
    const double mid = 0.5 * (lo + hi);
    const double h_prod = dot(y_prod, mech.hf_mass) + mech.hs_mix(mid, y_prod);
    if (h_prod < h_react) lo = mid;
    else hi = mid;
  }
  return 0.5 * (lo + hi);
}

void apply_ignition(
    const Config& cfg,
    const Mechanism& mech,
    const Grid& grid,
    std::vector<double>& T,
    const std::vector<std::vector<double>>& Y,
    Diagnostics& diag) {
  const int n = grid.n;
  std::vector<bool> mask(n, false);
  int count = 0;
  if (cfg.mixing_mode == "nonpremixed") {
    const double centre = 0.5 * (grid.r_min + grid.r_max);
    const double radius = std::max(cfg.ignition_region_m, grid.dr);
    for (int i = 0; i < n; ++i) {
      if (std::abs(grid.r_centers[i] - centre) <= radius) { mask[i] = true; ++count; }
    }
  } else {
    const double radius = std::max(cfg.ignition_region_m, grid.dr);
    for (int i = 0; i < n; ++i) {
      if (grid.r_centers[i] <= grid.r_min + radius) { mask[i] = true; ++count; }
    }
  }
  if (count == 0) {
    int best = 0;
    double best_d = std::abs(grid.r_centers[0] - (grid.r_min + grid.dr));
    for (int i = 1; i < n; ++i) {
      const double d = std::abs(grid.r_centers[i] - (grid.r_min + grid.dr));
      if (d < best_d) { best_d = d; best = i; }
    }
    mask[best] = true;
    count = 1;
  }

  double volume = 0.0, mean_rho = 0.0, mean_cp = 0.0;
  std::vector<double> y_kernel(mech.size(), 0.0);
  const double p0 = cfg.ambient_pressure_bar * 1e5;
  for (int i = 0; i < n; ++i) {
    if (!mask[i]) continue;
    const double rho = mech.density(T[i], p0, Y[i]);
    volume += grid.cell_volume[i];
    mean_rho += rho;
    mean_cp += mech.cp_mix(T[i], Y[i]);
    for (int k = 0; k < mech.size(); ++k) y_kernel[k] += Y[i][k];
  }
  mean_rho /= std::max(count, 1);
  mean_cp /= std::max(count, 1);
  for (double& v : y_kernel) v /= std::max(count, 1);

  const std::vector<double> y_ref =
      (cfg.mixing_mode == "premixed")
          ? premixed_composition(mech, cfg.equivalence_ratio, cfg.oxygen_pct, cfg.oxidizer)
          : y_kernel;
  const double t_ad = estimate_adiabatic_flame_temp(mech, cfg.ambient_temperature_k, y_ref);
  const double t_cap = std::min(t_ad + 300.0, 3500.0);

  if (cfg.ignition_method == "energy_deposition") {
    const double delta_t = cfg.ignition_energy_j /
                           std::max(mean_rho * mean_cp * volume, 1e-30);
    for (int i = 0; i < n; ++i) {
      if (mask[i]) T[i] = std::min(T[i] + delta_t, t_cap);
    }
  } else {
    for (int i = 0; i < n; ++i) {
      if (mask[i]) T[i] = std::min(cfg.ambient_temperature_k + 1800.0, t_cap);
    }
  }

  diag.kernel_cells = count;
  diag.kernel_radius_m = std::max(cfg.ignition_region_m, grid.dr);
  diag.adiabatic_flame_temp_k_estimate = t_ad;
  diag.ignition_cap_k = t_cap;
}

std::vector<double> continuity_velocity(
    const std::vector<double>& rho, double mass_flow, const Grid& grid) {
  std::vector<double> u(grid.n, 0.0);
  if (mass_flow <= 0.0) return u;
  for (int i = 0; i < grid.n; ++i) {
    if (grid.r_centers[i] > 0.0) {
      u[i] = mass_flow /
             (4.0 * PI * grid.r_centers[i] * grid.r_centers[i] * std::max(rho[i], 1e-30));
    }
  }
  return u;
}

double momentum_residual_max(
    const std::vector<double>& u, const Grid& grid, double g_r) {
  const std::vector<double> dudr = grid.gradient(u);
  double max_r = 0.0;
  for (int i = 0; i < grid.n; ++i) {
    max_r = std::max(max_r, std::abs(u[i] * dudr[i] - g_r));
  }
  return max_r;
}

double flame_radius(
    const std::vector<double>& T, const Grid& grid, double ambient) {
  double r = 0.0;
  for (int i = 0; i < grid.n; ++i) {
    if (T[i] > ambient + 200.0) r = std::max(r, grid.r_centers[i]);
  }
  return r;
}

double volume_fraction(
    const std::vector<double>& T, const Grid& grid, double ambient) {
  double hot = 0.0, total = 0.0;
  for (int i = 0; i < grid.n; ++i) {
    total += grid.cell_volume[i];
    if (T[i] > ambient + 200.0) hot += grid.cell_volume[i];
  }
  return hot / std::max(total, 1e-30);
}

double total_mass(const std::vector<double>& rho, const Grid& grid) {
  double m = 0.0;
  for (int i = 0; i < grid.n; ++i) m += rho[i] * grid.cell_volume[i];
  return m;
}

double total_enthalpy(
    const Mechanism& mech,
    const std::vector<double>& T,
    const std::vector<std::vector<double>>& Y,
    const std::vector<double>& rho,
    const Grid& grid) {
  double h = 0.0;
  for (int i = 0; i < grid.n; ++i) {
    h += rho[i] * (mech.hs_mix(T[i], Y[i]) + dot(Y[i], mech.hf_mass)) *
         grid.cell_volume[i];
  }
  return h;
}

double stability_score(bool quenched, const std::vector<HistoryRow>& history) {
  if (quenched) return 8.0;
  // Ignore the t=0 snapshot: it is the pre-run state, not combustion history.
  const int first_idx =
      (!history.empty() && history.front().iteration == 0) ? 1 : 0;
  if (static_cast<int>(history.size()) <= first_idx) return 0.0;
  const double first = history[first_idx].peak_temp_k;
  const double last = history.back().peak_temp_k;
  const double growth = std::max(last - first, 0.0);
  const int m = static_cast<int>(history.size());
  const int start = std::max(first_idx, m - 8);
  double mean = 0.0;
  for (int i = start; i < m; ++i) mean += history[i].peak_temp_k;
  mean /= std::max(m - start, 1);
  double var = 0.0;
  for (int i = start; i < m; ++i) {
    const double d = history[i].peak_temp_k - mean;
    var += d * d;
  }
  const double drift = std::sqrt(var / std::max(m - start, 1));
  const double base = 60.0 + std::min(growth, 400.0) * 0.05;
  return round_to(clampd(base - drift * 0.02, 5.0, 99.0), 1);
}

HistoryRow state_metrics(
    const Mechanism& mech,
    const Config& cfg,
    const Grid& grid,
    double t,
    int step,
    const std::vector<double>& T,
    const std::vector<std::vector<double>>& Y,
    const std::vector<double>& rho,
    const std::vector<double>& u,
    double g_r,
    int fuel_index,
    double initial_fuel_mass) {
  const double ambient = cfg.ambient_temperature_k;
  HistoryRow row;
  row.t_s = round_to(t, 6);
  row.iteration = step;
  row.max_flame_radius_m = round_to(flame_radius(T, grid, ambient), 6);
  row.peak_temp_k = round_to(*std::max_element(T.begin(), T.end()), 1);
  double mean_t = 0.0, total_v = 0.0;
  for (int i = 0; i < grid.n; ++i) {
    mean_t += T[i] * grid.cell_volume[i];
    total_v += grid.cell_volume[i];
  }
  row.mean_temp_k = round_to(mean_t / std::max(total_v, 1e-30), 1);
  double fuel_mass = 0.0;
  for (int i = 0; i < grid.n; ++i) {
    fuel_mass += rho[i] * Y[i][fuel_index] * grid.cell_volume[i];
  }
  row.fuel_burned_fraction =
      (initial_fuel_mass <= 0.0)
          ? 0.0
          : round_to(clampd(1.0 - fuel_mass / initial_fuel_mass, 0.0, 1.0), 4);
  const double flame_frac = volume_fraction(T, grid, ambient);
  row.soot_index = round_to(cfg.soot_tendency_index * flame_frac *
                                std::sqrt(std::max(cfg.ambient_pressure_bar, 1e-6)) *
                                (1.0 - std::min(cfg.oxygen_pct / 100.0, 0.95)) * 10.0,
                            4);
  row.buoyancy_ke = round_to(std::abs(g_r) * row.max_flame_radius_m, 6);
  row.momentum_residual_max = round_to(momentum_residual_max(u, grid, g_r), 6);

  double xi_max = 0.0, qdot_max = 0.0;
  for (int i = 0; i < grid.n; ++i) {
    std::vector<double> C(mech.size(), 0.0);
    for (int k = 0; k < mech.size(); ++k) C[k] = rho[i] * Y[i][k] / mech.W[k];
    const double xi = mech.rate_of_progress(T[i], C);
    xi_max = std::max(xi_max, xi);
    qdot_max = std::max(qdot_max, mech.heat_of_reaction * xi);
  }
  row.reaction_rate_max = round_to(xi_max, 4);
  row.heat_release_max_w_m3 = round_to(qdot_max, 3);
  return row;
}

std::vector<int> coarse_indices(int n, int m) {
  m = std::min(std::max(m, 1), n);
  std::vector<int> idx;
  for (int i = 0; i < m; ++i) {
    const int v = (m == 1) ? 0 : static_cast<int>(std::round(i * (n - 1.0) / (m - 1.0)));
    if (idx.empty() || idx.back() != v) idx.push_back(v);
  }
  return idx;
}

RadialSnapshot coarse_radial(
    const Mechanism& mech,
    const Grid& grid,
    double t,
    const std::vector<double>& T,
    const std::vector<std::vector<double>>& Y,
    const std::vector<double>& rho,
    const std::vector<double>& u) {
  RadialSnapshot s;
  s.t_s = round_to(t, 6);
  const std::vector<int> idx = coarse_indices(grid.n, COARSE_RADIAL_POINTS);
  const int fuel = mech.fuel_index;
  const int o2 = mech.o2_index;
  for (int i : idx) {
    s.r_m.push_back(round_to(grid.r_centers[i], 7));
    s.temperature_k.push_back(round_to(T[i], 2));
    s.density_kg_m3.push_back(round_to(rho[i], 6));
    s.velocity_ms.push_back(round_to(u[i], 7));
    s.fuel_mass_fraction.push_back(round_to(Y[i][fuel], 6));
    s.oxygen_mass_fraction.push_back(o2 >= 0 ? round_to(Y[i][o2], 6) : 0.0);
    std::vector<double> C(mech.size(), 0.0);
    for (int k = 0; k < mech.size(); ++k) C[k] = rho[i] * Y[i][k] / mech.W[k];
    const double xi = mech.rate_of_progress(T[i], C);
    s.reaction_rate_mol_m3_s.push_back(round_to(xi, 5));
    s.heat_release_w_m3.push_back(round_to(mech.heat_of_reaction * xi, 3));
  }
  return s;
}

void fill_full_radial(
    const Mechanism& mech,
    const Grid& grid,
    const std::vector<double>& T,
    const std::vector<std::vector<double>>& Y,
    const std::vector<double>& rho,
    const std::vector<double>& u,
    const std::vector<double>& hs,
    FinalOutput& final_out) {
  const int n = grid.n;
  const int ns = mech.size();
  final_out.r_m.resize(n);
  final_out.temperature_k.resize(n);
  final_out.density_kg_m3.resize(n);
  final_out.velocity_ms.resize(n);
  final_out.sensible_enthalpy_j_per_kg.resize(n);
  final_out.reaction_rate_mol_m3_s.resize(n);
  final_out.heat_release_w_m3.resize(n);
  final_out.molecular_weight_kg_mol.resize(n);
  final_out.mass_fractions.assign(ns, std::vector<double>(n, 0.0));
  final_out.molar_concentrations.assign(ns, std::vector<double>(n, 0.0));
  final_out.production_rates.assign(ns, std::vector<double>(n, 0.0));
  for (int i = 0; i < n; ++i) {
    std::vector<double> C(ns, 0.0);
    for (int k = 0; k < ns; ++k) C[k] = rho[i] * Y[i][k] / mech.W[k];
    const double xi = mech.rate_of_progress(T[i], C);
    final_out.r_m[i] = round_to(grid.r_centers[i], 8);
    final_out.temperature_k[i] = round_to(T[i], 3);
    final_out.density_kg_m3[i] = round_to(rho[i], 8);
    final_out.velocity_ms[i] = round_to(u[i], 9);
    final_out.sensible_enthalpy_j_per_kg[i] = round_to(hs[i], 3);
    final_out.reaction_rate_mol_m3_s[i] = round_to(xi, 6);
    final_out.heat_release_w_m3[i] = round_to(mech.heat_of_reaction * xi, 3);
    final_out.molecular_weight_kg_mol[i] =
        round_to(mech.molecular_weight(Y[i]), 8);
    for (int k = 0; k < ns; ++k) {
      final_out.mass_fractions[k][i] = round_to(Y[i][k], 8);
      final_out.molar_concentrations[k][i] = round_to(C[k], 8);
      final_out.production_rates[k][i] =
          round_to(mech.W[k] * mech.nu[k] * xi, 6);
    }
  }
}

std::vector<std::vector<double>> paint_temperature(
    const Grid& grid, const std::vector<double>& T, int nx, int ny,
    double inner_temperature, double outer_temperature) {
  std::vector<std::vector<double>> frame(ny, std::vector<double>(nx, 0.0));
  const double length = 2.0 * grid.r_max;
  for (int j = 0; j < ny; ++j) {
    const double y = -length / 2.0 + (j + 0.5) * (length / ny);
    for (int i = 0; i < nx; ++i) {
      const double x = -length / 2.0 + (i + 0.5) * (length / nx);
      const double rr = std::hypot(x, y);
      double value;
      if (rr <= grid.r_centers[0]) {
        value = T[0];
      } else if (rr >= grid.r_centers[grid.n - 1]) {
        value = T[grid.n - 1];
      } else {
        int hi = 1;
        while (hi < grid.n && grid.r_centers[hi] < rr) ++hi;
        const int lo = std::max(hi - 1, 0);
        const double w = (rr - grid.r_centers[lo]) /
                         std::max(grid.r_centers[hi] - grid.r_centers[lo], 1e-30);
        value = T[lo] + w * (T[hi] - T[lo]);
      }
      if (rr <= grid.r_min) value = inner_temperature;
      if (rr >= grid.r_max) value = outer_temperature;
      frame[j][i] = round_to(value, 1);
    }
  }
  return frame;
}

void advance_substep(
    const Config& cfg,
    const Mechanism& mech,
    const Grid& grid,
    std::vector<double>& T,
    std::vector<std::vector<double>>& Y,
    std::vector<double>& rho,
    std::vector<double>& u,
    double p0,
    double g_r,
    const Boundaries& b,
    double dt,
    Diagnostics& diag) {
  const int n = grid.n;
  const int ns = mech.size();
  std::vector<double> cp(n), lam(n), rho_face(n + 1), lam_face(n + 1);
  std::vector<std::vector<double>> D(n, std::vector<double>(ns, 0.0));
  std::vector<std::vector<double>> D_face(n + 1, std::vector<double>(ns, 0.0));
  for (int i = 0; i < n; ++i) {
    cp[i] = std::max(mech.cp_mix(T[i], Y[i]), 1.0);
    lam[i] = mech.lambda_mix(T[i], Y[i]);
    for (int k = 0; k < ns; ++k) D[i][k] = mech.species[k].diffusivity(T[i], p0);
  }
  rho_face = grid.face_average(rho);
  lam_face = grid.face_average(lam);
  for (int f = 0; f <= n; ++f) {
    for (int k = 0; k < ns; ++k) {
      D_face[f][k] = (f == 0) ? D[0][k]
                              : (f == n) ? D[n - 1][k] : 0.5 * (D[f - 1][k] + D[f][k]);
    }
  }

  std::vector<std::vector<double>> Y_new = implicit_diffusion_species(
      Y, dt, grid, rho, D_face, b.Y_inner, b.Y_outer, cfg.inner_bc, cfg.outer_bc);
  std::vector<double> T_new = implicit_diffusion_temperature(
      T, dt, grid, rho, cp, lam_face, b.T_inner, b.T_outer, cfg.inner_bc, cfg.outer_bc);

  Y_new = upwind_advection_species(
      Y_new, u, dt, grid, b.Y_inner, b.Y_outer, cfg.inner_bc, cfg.outer_bc);
  T_new = upwind_advection_1d(
      T_new, u, dt, grid, b.T_inner, b.T_outer, cfg.inner_bc, cfg.outer_bc);
  for (int i = 0; i < n; ++i) {
    normalise_Y(Y_new[i], mech.n2_index);
    T_new[i] = clampd(T_new[i], 200.0, 6000.0);
  }

  const FluxBundle fluxes = diffusive_fluxes(
      Y_new, grid, rho, D_face, b.Y_inner, b.Y_outer, cfg.inner_bc, cfg.outer_bc);
  const std::vector<std::vector<double>> div_corr =
      divergence_species(fluxes.j_corr, grid);
  for (int i = 0; i < n; ++i) {
    for (int k = 0; k < ns; ++k) {
      Y_new[i][k] -= dt * div_corr[i][k] / std::max(rho[i], 1e-30);
    }
    normalise_Y(Y_new[i], mech.n2_index);
  }

  const std::vector<double> e_flux =
      species_enthalpy_flux(mech, T_new, fluxes.j_total, grid);
  const std::vector<double> div_e = grid.divergence(e_flux);
  for (int i = 0; i < n; ++i) {
    T_new[i] -= dt * div_e[i] / (std::max(rho[i], 1e-30) * cp[i]);
    T_new[i] = clampd(T_new[i], 200.0, 6000.0);
  }

  integrate_chemistry(mech, T_new, Y_new, rho, dt, diag);

  std::vector<double> rho_after(n);
  for (int i = 0; i < n; ++i) rho_after[i] = mech.density(T_new[i], p0, Y_new[i]);
  double max_drho = 0.0;
  for (int i = 0; i < n; ++i) {
    const double drho = rho_after[i] - rho[i];
    max_drho = std::max(max_drho, std::abs(drho) / std::max(rho[i], 1e-30));
    for (int k = 0; k < ns; ++k) {
      Y_new[i][k] -= Y_new[i][k] * drho / std::max(rho[i], 1e-30);
    }
    normalise_Y(Y_new[i], mech.n2_index);
    const double hs_now = mech.hs_mix(T_new[i], Y_new[i]);
    T_new[i] -= hs_now / (std::max(rho[i], 1e-30) * cp[i]) * drho;
    T_new[i] = clampd(T_new[i], 200.0, 6000.0);
  }
  diag.max_drho_over_rho = max_drho;

  for (int i = 0; i < n; ++i) {
    normalise_Y(Y_new[i], mech.n2_index);
    rho[i] = mech.density(T_new[i], p0, Y_new[i]);
  }
  u = continuity_velocity(rho, cfg.mass_flow_kg_s, grid);
  T = T_new;
  Y = Y_new;
}

}  // namespace

SimOutput run_simulation(const Config& cfg, const Mechanism& mech) {
  SimOutput out;
  out.species_keys = mech.keys;
  out.reaction_key = cfg.reaction.empty() ? (cfg.fuel + "_O2") : cfg.reaction;

  Grid grid(cfg.r_min_m, cfg.r_max_m, cfg.Nr);
  const double p0 = cfg.ambient_pressure_bar * 1e5;
  const double t0 = cfg.ambient_temperature_k;
  const double g_r = cfg.has_radial_gravity ? cfg.radial_gravity_m_per_s2
                                            : -gravity_magnitude(cfg);

  std::vector<double> T(grid.n, t0);
  std::vector<std::vector<double>> Y = initial_composition(cfg, mech, grid);
  Diagnostics diag;
  diag.radial_gravity_m_per_s2 = g_r;
  apply_ignition(cfg, mech, grid, T, Y, diag);
  for (int i = 0; i < grid.n; ++i) normalise_Y(Y[i], mech.n2_index);

  std::vector<double> rho(grid.n), u(grid.n), hs(grid.n);
  for (int i = 0; i < grid.n; ++i) rho[i] = mech.density(T[i], p0, Y[i]);
  u = continuity_velocity(rho, cfg.mass_flow_kg_s, grid);
  for (int i = 0; i < grid.n; ++i) hs[i] = mech.hs_mix(T[i], Y[i]);

  const Boundaries b = boundary_compositions(cfg, mech);
  double initial_fuel_mass = 0.0;
  for (int i = 0; i < grid.n; ++i) {
    initial_fuel_mass += rho[i] * Y[i][mech.fuel_index] * grid.cell_volume[i];
  }
  const double mass_initial = total_mass(rho, grid);
  const double enthalpy_initial = total_enthalpy(mech, T, Y, rho, grid);

  double t = 0.0;
  double peak_t = *std::max_element(T.begin(), T.end());
  bool quenched = false;
  bool has_quench_time = false;
  double quench_time = 0.0;
  double last_radius = 0.0;
  double last_save_t = 0.0;

  // Save the pre-ignition state so every streamed series starts at t = 0 /
  // iteration 0 instead of the first output-interval step (4 by default).
  {
    HistoryRow row = state_metrics(mech, cfg, grid, 0.0, 0, T, Y, rho, u, g_r,
                                   mech.fuel_index, initial_fuel_mass);
    out.history.push_back(row);
    out.times.push_back(0.0);
    out.frames.push_back(
        paint_temperature(grid, T, cfg.nx, cfg.ny, b.T_inner, b.T_outer));
    out.radial_frames.push_back(coarse_radial(mech, grid, 0.0, T, Y, rho, u));
    last_radius = row.max_flame_radius_m;
  }

  for (int step = 1; step <= cfg.iteration_count; ++step) {
    double dt_remaining = cfg.dt_s;
    int sub = 0;
    while (dt_remaining > 1e-15) {
      double max_u = 0.0;
      for (double v : u) max_u = std::max(max_u, std::abs(v));
      const double dt_cfl = 0.4 * grid.dr / std::max(max_u, 1e-12);
      double dt_sub = std::min(dt_remaining, dt_cfl);
      const double min_dt = dt_remaining / static_cast<double>(MAX_SUBSTEPS_PER_OUTER);
      if (dt_sub < min_dt) {
        dt_sub = min_dt;
        diag.substeps_capped = true;
      }
      if (dt_sub <= 0.0) dt_sub = dt_remaining;
      advance_substep(cfg, mech, grid, T, Y, rho, u, p0, g_r, b, dt_sub, diag);
      dt_remaining -= dt_sub;
      t += dt_sub;
      ++sub;
      ++diag.substeps_total;
      peak_t = std::max(peak_t, *std::max_element(T.begin(), T.end()));
      if (sub >= MAX_SUBSTEPS_PER_OUTER && dt_remaining > 1e-15) {
        advance_substep(cfg, mech, grid, T, Y, rho, u, p0, g_r, b, dt_remaining, diag);
        t += dt_remaining;
        dt_remaining = 0.0;
        ++diag.substeps_total;
        diag.substeps_capped = true;
      }
    }

    if (step > 1 && !quenched) {
      const double max_t = *std::max_element(T.begin(), T.end());
      if (max_t < t0 + 150.0) {
        quenched = true;
        has_quench_time = true;
        quench_time = t;
      }
    }

    const bool save = (step % std::max(cfg.output_interval_steps, 1) == 0) ||
                      (step == cfg.iteration_count);
    if (save) {
      HistoryRow row = state_metrics(
          mech, cfg, grid, t, step, T, Y, rho, u, g_r, mech.fuel_index,
          initial_fuel_mass);
      if (row.t_s > last_save_t) {
        row.flame_speed_m_per_s = round_to(
            (row.max_flame_radius_m - last_radius) / std::max(row.t_s - last_save_t, 1e-30),
            6);
      }
      last_radius = row.max_flame_radius_m;
      last_save_t = row.t_s;
      out.history.push_back(row);
      out.times.push_back(row.t_s);
      out.frames.push_back(
          paint_temperature(grid, T, cfg.nx, cfg.ny, b.T_inner, b.T_outer));
      out.radial_frames.push_back(coarse_radial(mech, grid, t, T, Y, rho, u));
    }
  }

  FinalOutput& f = out.final;
  f.quenched = quenched;
  f.has_quench_time = has_quench_time;
  f.quench_time_s = quench_time;
  f.peak_temp_k = round_to(peak_t, 1);
  f.max_flame_radius_m = round_to(flame_radius(T, grid, t0), 6);
  const HistoryRow last = state_metrics(
      mech, cfg, grid, t, cfg.iteration_count, T, Y, rho, u, g_r,
      mech.fuel_index, initial_fuel_mass);
  f.soot_volume_fraction = round_to(last.soot_index * 1e-3, 8);
  f.stability = stability_score(quenched, out.history);
  fill_full_radial(mech, grid, T, Y, rho, u, hs, f);

  diag.momentum_residual_max = round_to(momentum_residual_max(u, grid, g_r), 6);
  diag.mass_relative_error = round_to(
      (total_mass(rho, grid) - mass_initial - cfg.mass_flow_kg_s * t) /
          std::max(std::abs(mass_initial), 1e-30),
      8);
  diag.enthalpy_relative_change = round_to(
      (total_enthalpy(mech, T, Y, rho, grid) - enthalpy_initial) /
          std::max(std::abs(enthalpy_initial), 1e-30),
      8);
  diag.boundary_mass_flux_kg_s =
      round_to(rho[grid.n - 1] * u[grid.n - 1] * grid.face_area[grid.n], 10);
  diag.run_end_time_s = round_to(t, 6);
  f.diagnostics = diag;
  return out;
}

}  // namespace triage
