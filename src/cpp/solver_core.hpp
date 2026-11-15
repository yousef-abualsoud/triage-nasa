#pragma once

#include <map>
#include <string>
#include <vector>

namespace triage {

struct Species {
  std::string key;
  std::string formula;
  double W = 0.0;       // kg/mol
  double hf = 0.0;      // J/mol
  bool has_nasa = false;
  double nasa_low[7] = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0};
  double nasa_high[7] = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0};
  double t_mid = 1000.0;
  double cp_const = 0.0;  // J/(kg K), when has_nasa == false
  double k_ref = 0.026;
  double k_t_ref = 300.0;
  double k_exp = 0.7;
  double mu_ref = 1.8e-5;
  double mu_t_ref = 300.0;
  double mu_exp = 0.7;
  double d_ref = 2.0e-5;
  double d_t_ref = 300.0;
  double d_exp = 1.75;

  double cp_mass(double T) const;
  double hs_mass(double T) const;
  double hf_mass() const { return hf / W; }
  double thermal_conductivity(double T) const;
  double viscosity(double T) const;
  double diffusivity(double T, double pressure_pa) const;
};

struct Mechanism {
  std::vector<Species> species;
  std::vector<std::string> keys;
  std::vector<double> W;
  std::vector<double> hf_mass;
  std::vector<double> nu;
  std::vector<double> orders;
  double A = 0.0;
  double beta = 0.0;
  double Ea = 0.0;
  double heat_of_reaction = 0.0;  // J/mol fuel
  int fuel_index = 0;
  int o2_index = -1;
  int n2_index = -1;
  double t_ref = 298.15;
  double p_ref = 101325.0;
  double r_univ = 8.314462;

  int size() const { return static_cast<int>(species.size()); }
  double cp_species(int k, double T) const;
  double hs_species(int k, double T) const;
  double cp_mix(double T, const std::vector<double>& Y) const;
  double hs_mix(double T, const std::vector<double>& Y) const;
  double lambda_mix(double T, const std::vector<double>& Y) const;
  double molecular_weight(const std::vector<double>& Y) const;
  double density(double T, double p0, const std::vector<double>& Y) const;
  double rate_of_progress(double T, const std::vector<double>& C) const;
  double temperature_from_hs(double hs_target, const std::vector<double>& Y, double T_guess) const;
};

struct Config {
  std::string fuel = "CH4";
  std::string geometry = "spherical_1d";
  double oxygen_pct = 21.0;
  double ambient_pressure_bar = 1.0;
  double ambient_temperature_k = 300.0;
  std::string gravity_mode = "zero_g";
  double custom_gravity_m_per_s2 = 3.7;
  double custom_g_jitter_m_per_s2 = 0.0;
  bool has_radial_gravity = false;
  double radial_gravity_m_per_s2 = 0.0;
  std::string ignition_method = "energy_deposition";
  double ignition_energy_j = 2.0;
  double ignition_region_m = 0.003;
  double r_min_m = 0.001;
  double r_max_m = 0.04;
  int Nr = 256;
  double mass_flow_kg_s = 0.0;
  std::string mixing_mode = "premixed";
  double equivalence_ratio = 1.0;
  std::string oxidizer = "air";
  std::string reaction;
  bool has_inlet_temperature = false;
  double inlet_temperature_k = 300.0;
  std::string inner_bc = "fixed";
  std::string outer_bc = "fixed";
  std::map<std::string, double> initial_species_mass_fractions;
  std::map<std::string, double> fuel_inlet_composition;
  std::map<std::string, double> oxidizer_inlet_composition;
  int nx = 128;
  int ny = 128;
  double dt_s = 1e-3;
  int iteration_count = 200;
  int output_interval_steps = 4;
  double soot_tendency_index = 0.1;
};

struct Grid {
  double r_min = 0.0;
  double r_max = 0.04;
  int n = 1;
  double dr = 0.04;
  std::vector<double> r_faces;
  std::vector<double> r_centers;
  std::vector<double> face_area;
  std::vector<double> cell_volume;

  Grid(double r_min_, double r_max_, int n_);
  std::vector<double> face_average(const std::vector<double>& cell_values) const;
  std::vector<double> gradient(const std::vector<double>& cell_values) const;
  std::vector<double> face_gradient(const std::vector<double>& cell_values) const;
  std::vector<double> divergence(const std::vector<double>& face_flux) const;
};

struct HistoryRow {
  double t_s = 0.0;
  double max_flame_radius_m = 0.0;
  double peak_temp_k = 0.0;
  double mean_temp_k = 0.0;
  double fuel_burned_fraction = 0.0;
  double soot_index = 0.0;
  double buoyancy_ke = 0.0;
  double reaction_rate_max = 0.0;
  double heat_release_max_w_m3 = 0.0;
  double momentum_residual_max = 0.0;
  double flame_speed_m_per_s = 0.0;
  int iteration = 0;
};

struct RadialSnapshot {
  double t_s = 0.0;
  std::vector<double> r_m;
  std::vector<double> temperature_k;
  std::vector<double> density_kg_m3;
  std::vector<double> velocity_ms;
  std::vector<double> fuel_mass_fraction;
  std::vector<double> oxygen_mass_fraction;
  std::vector<double> reaction_rate_mol_m3_s;
  std::vector<double> heat_release_w_m3;
};

struct Diagnostics {
  double momentum_residual_max = 0.0;
  double mass_relative_error = 0.0;
  double enthalpy_relative_change = 0.0;
  double max_drho_over_rho = 0.0;
  int substeps_total = 0;
  bool substeps_capped = false;
  double boundary_mass_flux_kg_s = 0.0;
  double run_end_time_s = 0.0;
  double radial_gravity_m_per_s2 = 0.0;
  double adiabatic_flame_temp_k_estimate = 0.0;
  double ignition_cap_k = 0.0;
  int kernel_cells = 0;
  double kernel_radius_m = 0.0;
  double chem_xi_dot_max = 0.0;
  double chem_xi_actual_max = 0.0;
  double chem_heat_release_max = 0.0;
  double chem_reacted_extent = 0.0;
};

struct FinalOutput {
  bool quenched = false;
  bool has_quench_time = false;
  double quench_time_s = 0.0;
  double peak_temp_k = 0.0;
  double max_flame_radius_m = 0.0;
  double soot_volume_fraction = 0.0;
  double stability = 0.0;
  std::vector<double> r_m;
  std::vector<double> temperature_k;
  std::vector<double> density_kg_m3;
  std::vector<double> velocity_ms;
  std::vector<double> sensible_enthalpy_j_per_kg;
  std::vector<double> reaction_rate_mol_m3_s;
  std::vector<double> heat_release_w_m3;
  std::vector<double> molecular_weight_kg_mol;
  std::vector<std::vector<double>> mass_fractions;     // [species][cell]
  std::vector<std::vector<double>> molar_concentrations;
  std::vector<std::vector<double>> production_rates;
  Diagnostics diagnostics;
};

struct SimOutput {
  std::vector<std::vector<std::vector<double>>> frames;  // [frame][ny][nx]
  std::vector<double> times;
  std::vector<HistoryRow> history;
  FinalOutput final;
  std::vector<RadialSnapshot> radial_frames;
  std::string reaction_key;
  std::vector<std::string> species_keys;
};

SimOutput run_simulation(const Config& cfg, const Mechanism& mech);

}  // namespace triage
