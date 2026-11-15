#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <map>
#include <string>
#include <vector>

#include "solver_core.hpp"

namespace py = pybind11;
using namespace triage;

namespace {

template <typename T>
T get_value(const py::dict& d, const char* key, const T& fallback) {
  if (!d.contains(key)) return fallback;
  py::handle h = d[key];
  if (h.is_none()) return fallback;
  return py::cast<T>(h);
}

std::map<std::string, double> get_map(const py::dict& d, const char* key) {
  if (!d.contains(key)) return {};
  py::handle h = d[key];
  if (h.is_none()) return {};
  return py::cast<std::map<std::string, double>>(h);
}

std::vector<double> as_double_list(py::handle h) {
  if (h.is_none()) return {};
  return py::cast<std::vector<double>>(h);
}

std::vector<std::string> as_string_list(py::handle h) {
  if (h.is_none()) return {};
  return py::cast<std::vector<std::string>>(h);
}

Species parse_species(py::handle handle) {
  py::dict d = py::cast<py::dict>(handle);
  Species s;
  s.key = get_value<std::string>(d, "key", "");
  s.formula = get_value<std::string>(d, "formula", s.key);
  s.W = get_value<double>(d, "molecular_weight", 0.0);
  s.hf = get_value<double>(d, "heat_of_formation", 0.0);
  s.cp_const = get_value<double>(d, "cp_constant", 0.0);
  if (d.contains("nasa7") && !d["nasa7"].is_none()) {
    py::dict n = py::cast<py::dict>(d["nasa7"]);
    s.has_nasa = true;
    s.t_mid = get_value<double>(n, "t_mid", 1000.0);
    const std::vector<double> low = as_double_list(n["low"]);
    const std::vector<double> high = as_double_list(n["high"]);
    for (int i = 0; i < 7 && i < static_cast<int>(low.size()); ++i) s.nasa_low[i] = low[i];
    for (int i = 0; i < 7 && i < static_cast<int>(high.size()); ++i) s.nasa_high[i] = high[i];
  }
  if (d.contains("thermal_conductivity")) {
    py::dict t = py::cast<py::dict>(d["thermal_conductivity"]);
    s.k_ref = get_value<double>(t, "ref", 0.026);
    s.k_t_ref = get_value<double>(t, "t_ref", 300.0);
    s.k_exp = get_value<double>(t, "exponent", 0.7);
  }
  if (d.contains("viscosity")) {
    py::dict t = py::cast<py::dict>(d["viscosity"]);
    s.mu_ref = get_value<double>(t, "ref", 1.8e-5);
    s.mu_t_ref = get_value<double>(t, "t_ref", 300.0);
    s.mu_exp = get_value<double>(t, "exponent", 0.7);
  }
  if (d.contains("diffusivity")) {
    py::dict t = py::cast<py::dict>(d["diffusivity"]);
    s.d_ref = get_value<double>(t, "ref", 2.0e-5);
    s.d_t_ref = get_value<double>(t, "t_ref", 300.0);
    s.d_exp = get_value<double>(t, "exponent", 1.75);
  }
  return s;
}

Mechanism parse_mechanism(const py::dict& d) {
  Mechanism m;
  py::list species_list = py::cast<py::list>(d["species"]);
  for (py::handle h : species_list) m.species.push_back(parse_species(h));
  m.keys = as_string_list(d["species_keys"]);
  m.nu = as_double_list(d["nu"]);
  m.orders = as_double_list(d["orders"]);
  m.fuel_index = get_value<int>(d, "fuel_index", 0);
  m.o2_index = get_value<int>(d, "o2_index", -1);
  m.n2_index = get_value<int>(d, "n2_index", -1);
  m.heat_of_reaction = get_value<double>(d, "heat_of_reaction_j_per_mol_fuel", 0.0);
  if (d.contains("constants")) {
    py::dict c = py::cast<py::dict>(d["constants"]);
    m.r_univ = get_value<double>(c, "R_univ", 8.314462);
    m.t_ref = get_value<double>(c, "T_ref", 298.15);
    m.p_ref = get_value<double>(c, "P_ref", 101325.0);
  }
  if (d.contains("reaction")) {
    py::dict r = py::cast<py::dict>(d["reaction"]);
    m.A = get_value<double>(r, "pre_exponential_factor", 0.0);
    m.beta = get_value<double>(r, "temperature_exponent", 0.0);
    m.Ea = get_value<double>(r, "activation_energy", 0.0);
  }
  // W and hf_mass must follow the species order (the payload's "species"
  // objects also carry them; the flat list is authoritative for the solver).
  m.W.clear();
  m.hf_mass.clear();
  for (const Species& s : m.species) {
    m.W.push_back(s.W);
    m.hf_mass.push_back(s.hf / s.W);
  }
  return m;
}

Config parse_config(const py::dict& d) {
  Config c;
  c.fuel = get_value<std::string>(d, "fuel", "CH4");
  c.geometry = get_value<std::string>(d, "geometry", "spherical_1d");
  c.oxygen_pct = get_value<double>(d, "oxygen_pct", 21.0);
  c.ambient_pressure_bar = get_value<double>(d, "ambient_pressure_bar", 1.0);
  c.ambient_temperature_k = get_value<double>(d, "ambient_temperature_k", 300.0);
  c.gravity_mode = get_value<std::string>(d, "gravity_mode", "zero_g");
  c.custom_gravity_m_per_s2 = get_value<double>(d, "custom_gravity_m_per_s2", 3.7);
  c.custom_g_jitter_m_per_s2 = get_value<double>(d, "custom_g_jitter_m_per_s2", 0.0);
  c.has_radial_gravity = d.contains("radial_gravity_m_per_s2") &&
                         !d["radial_gravity_m_per_s2"].is_none();
  if (c.has_radial_gravity) {
    c.radial_gravity_m_per_s2 = get_value<double>(d, "radial_gravity_m_per_s2", 0.0);
  }
  c.ignition_method = get_value<std::string>(d, "ignition_method", "energy_deposition");
  c.ignition_energy_j = get_value<double>(d, "ignition_energy_j", 2.0);
  c.ignition_region_m = get_value<double>(d, "ignition_region_m", 0.003);
  c.r_min_m = get_value<double>(d, "r_min_m", 0.001);
  c.r_max_m = get_value<double>(d, "r_max_m", 0.04);
  c.Nr = get_value<int>(d, "Nr", 256);
  c.mass_flow_kg_s = get_value<double>(d, "mass_flow_kg_s", 0.0);
  c.mixing_mode = get_value<std::string>(d, "mixing_mode", "premixed");
  c.equivalence_ratio = get_value<double>(d, "equivalence_ratio", 1.0);
  c.oxidizer = get_value<std::string>(d, "oxidizer", "air");
  c.reaction = get_value<std::string>(d, "reaction", "");
  c.has_inlet_temperature = d.contains("inlet_temperature_k") &&
                            !d["inlet_temperature_k"].is_none();
  if (c.has_inlet_temperature) {
    c.inlet_temperature_k = get_value<double>(d, "inlet_temperature_k", 300.0);
  }
  c.inner_bc = get_value<std::string>(d, "inner_bc", "fixed");
  c.outer_bc = get_value<std::string>(d, "outer_bc", "fixed");
  c.initial_species_mass_fractions = get_map(d, "initial_species_mass_fractions");
  c.fuel_inlet_composition = get_map(d, "fuel_inlet_composition");
  c.oxidizer_inlet_composition = get_map(d, "oxidizer_inlet_composition");
  c.nx = get_value<int>(d, "nx", 128);
  c.ny = get_value<int>(d, "ny", 128);
  c.dt_s = get_value<double>(d, "dt_s", 1e-3);
  c.iteration_count = get_value<int>(d, "iteration_count", 200);
  c.output_interval_steps = get_value<int>(d, "output_interval_steps", 4);
  return c;
}

py::list list_of_doubles(const std::vector<double>& values) {
  py::list out;
  for (double v : values) out.append(v);
  return out;
}

py::dict output_to_dict(const SimOutput& out, const Config& cfg) {
  py::dict result;
  py::list frames;
  for (const auto& frame : out.frames) {
    py::list rows;
    for (const auto& row : frame) rows.append(list_of_doubles(row));
    frames.append(rows);
  }
  result["frames"] = frames;

  py::list times;
  for (double t : out.times) times.append(t);
  result["times"] = times;

  py::list history;
  for (const auto& h : out.history) {
    py::dict row;
    row["t_s"] = h.t_s;
    row["max_flame_radius_m"] = h.max_flame_radius_m;
    row["peak_temp_k"] = h.peak_temp_k;
    row["mean_temp_k"] = h.mean_temp_k;
    row["fuel_burned_fraction"] = h.fuel_burned_fraction;
    row["soot_index"] = h.soot_index;
    row["buoyancy_ke"] = h.buoyancy_ke;
    row["reaction_rate_max"] = h.reaction_rate_max;
    row["heat_release_max_w_m3"] = h.heat_release_max_w_m3;
    row["momentum_residual_max"] = h.momentum_residual_max;
    row["flame_speed_m_per_s"] = h.flame_speed_m_per_s;
    row["iteration"] = h.iteration;
    history.append(row);
  }
  result["history"] = history;

  const FinalOutput& f = out.final;
  py::dict final;
  final["quenched"] = f.quenched;
  if (f.has_quench_time) final["quench_time_s"] = f.quench_time_s;
  else final["quench_time_s"] = py::none();
  final["peak_temp_k"] = f.peak_temp_k;
  final["max_flame_radius_m"] = f.max_flame_radius_m;
  final["soot_volume_fraction"] = f.soot_volume_fraction;
  final["stability"] = f.stability;

  py::dict radial;
  radial["r_m"] = list_of_doubles(f.r_m);
  radial["temperature_k"] = list_of_doubles(f.temperature_k);
  radial["density_kg_m3"] = list_of_doubles(f.density_kg_m3);
  radial["velocity_ms"] = list_of_doubles(f.velocity_ms);
  radial["sensible_enthalpy_j_per_kg"] = list_of_doubles(f.sensible_enthalpy_j_per_kg);
  radial["reaction_rate_mol_m3_s"] = list_of_doubles(f.reaction_rate_mol_m3_s);
  radial["heat_release_w_m3"] = list_of_doubles(f.heat_release_w_m3);
  radial["molecular_weight_kg_mol"] = list_of_doubles(f.molecular_weight_kg_mol);
  py::dict mass_fractions, molar_concentrations, production_rates;
  for (std::size_t k = 0; k < out.species_keys.size(); ++k) {
    mass_fractions[py::str(out.species_keys[k])] = list_of_doubles(f.mass_fractions[k]);
    molar_concentrations[py::str(out.species_keys[k])] =
        list_of_doubles(f.molar_concentrations[k]);
    production_rates[py::str(out.species_keys[k])] =
        list_of_doubles(f.production_rates[k]);
  }
  radial["mass_fractions"] = mass_fractions;
  radial["molar_concentrations_mol_m3"] = molar_concentrations;
  radial["production_rates_kg_m3_s"] = production_rates;
  final["radial"] = radial;

  const Diagnostics& d = f.diagnostics;
  py::dict diag;
  diag["momentum_residual_max"] = d.momentum_residual_max;
  diag["mass_relative_error"] = d.mass_relative_error;
  diag["enthalpy_relative_change"] = d.enthalpy_relative_change;
  diag["substeps_total"] = d.substeps_total;
  diag["substeps_capped"] = d.substeps_capped;
  diag["max_drho_over_rho"] = d.max_drho_over_rho;
  diag["boundary_mass_flux_kg_s"] = d.boundary_mass_flux_kg_s;
  diag["run_end_time_s"] = d.run_end_time_s;
  diag["radial_gravity_m_per_s2"] = d.radial_gravity_m_per_s2;

  py::dict ignition;
  ignition["kernel_cells"] = d.kernel_cells;
  ignition["kernel_radius_m"] = d.kernel_radius_m;
  ignition["adiabatic_flame_temp_k_estimate"] = d.adiabatic_flame_temp_k_estimate;
  ignition["ignition_cap_k"] = d.ignition_cap_k;
  diag["ignition"] = ignition;

  py::dict chem;
  chem["xi_dot_max"] = d.chem_xi_dot_max;
  chem["xi_actual_max"] = d.chem_xi_actual_max;
  chem["heat_release_max_w_m3"] = d.chem_heat_release_max;
  chem["reacted_extent_mol_m3"] = d.chem_reacted_extent;
  diag["chem_last"] = chem;

  py::dict geometry;
  geometry["type"] = "spherical_1d";
  geometry["r_min_m"] = cfg.r_min_m;
  geometry["r_max_m"] = cfg.r_max_m;
  geometry["Nr"] = cfg.Nr;
  geometry["nx_display"] = cfg.nx;
  geometry["ny_display"] = cfg.ny;
  diag["geometry"] = geometry;

  py::dict mechanism;
  mechanism["fuel"] = cfg.fuel;
  mechanism["reaction"] = out.reaction_key;
  mechanism["species"] = py::cast(out.species_keys);
  diag["mechanism"] = mechanism;

  final["diagnostics"] = diag;
  result["final"] = final;

  py::list radial_frames;
  for (const auto& s : out.radial_frames) {
    py::dict item;
    item["t_s"] = s.t_s;
    item["r_m"] = list_of_doubles(s.r_m);
    item["temperature_k"] = list_of_doubles(s.temperature_k);
    item["density_kg_m3"] = list_of_doubles(s.density_kg_m3);
    item["velocity_ms"] = list_of_doubles(s.velocity_ms);
    item["fuel_mass_fraction"] = list_of_doubles(s.fuel_mass_fraction);
    item["oxygen_mass_fraction"] = list_of_doubles(s.oxygen_mass_fraction);
    item["reaction_rate_mol_m3_s"] = list_of_doubles(s.reaction_rate_mol_m3_s);
    item["heat_release_w_m3"] = list_of_doubles(s.heat_release_w_m3);
    radial_frames.append(item);
  }
  result["radial_frames"] = radial_frames;
  return result;
}

py::dict run_py(py::dict config, py::dict mechanism) {
  Config cfg = parse_config(config);
  Mechanism mech = parse_mechanism(mechanism);
  cfg.soot_tendency_index = get_value<double>(mechanism, "soot_tendency_index", 0.1);
  const SimOutput out = run_simulation(cfg, mech);
  return output_to_dict(out, cfg);
}

}  // namespace

PYBIND11_MODULE(triage_core, m) {
  m.doc() = "T.R.I.A.G.E. 1D spherical combustion solver (C++ port of the document architecture)";
  m.def("run_simulation", &run_py, "Run one 1D spherical simulation",
        py::arg("config"), py::arg("mechanism"));
}
