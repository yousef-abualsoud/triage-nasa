"""Database, thermochemistry, and stoichiometry fidelity tests (doc §2–§3, §5.5–5.6)."""

from __future__ import annotations

import numpy as np
import pytest

from mechanism import (
    Mechanism,
    R_UNIV,
    T_REF,
    derive_stoichiometry,
    load_reactions,
    load_species,
    mechanism_payload,
    parse_formula,
    validate_reaction,
)


def test_all_builtin_reactions_validate():
    species = load_species()
    reactions = load_reactions()
    assert set(reactions) == {"CH4_O2", "C2H4_O2", "C3H8_O2", "H2_O2"}
    for reaction in reactions.values():
        validate_reaction(reaction, species)


@pytest.mark.parametrize(
    ("formula", "o2_per_fuel", "products"),
    [
        ("CH4", 2.0, {"CO2": 1.0, "H2O": 2.0}),
        ("C2H4", 3.0, {"CO2": 2.0, "H2O": 2.0}),
        ("C3H8", 5.0, {"CO2": 3.0, "H2O": 4.0}),
        ("H2", 0.5, {"H2O": 1.0}),
    ],
)
def test_formula_stoichiometry(formula, o2_per_fuel, products):
    stoich = derive_stoichiometry(formula)
    assert stoich is not None
    assert stoich["o2_per_fuel_mol"] == pytest.approx(o2_per_fuel)
    assert stoich["products"].keys() == products.keys()
    for key, value in products.items():
        assert stoich["products"][key] == pytest.approx(value)


def test_formula_parser_allows_o2_and_n2_but_rejects_bad_strings():
    assert parse_formula("O2") == {"O": 2.0}
    assert parse_formula("N2") == {"N": 2.0}
    assert parse_formula("C2H6O") == {"C": 2.0, "H": 6.0, "O": 1.0}
    assert parse_formula("C2H4(OH)2") is None
    assert parse_formula("Ar2") is None


@pytest.mark.parametrize(
    ("fuel", "expected_lhv_mj_per_kg"),
    [("CH4", 50.01), ("C2H4", 47.16), ("C3H8", 46.34), ("H2", 119.95)],
)
def test_heat_of_reaction_matches_formation_enthalpies(fuel, expected_lhv_mj_per_kg):
    mech = Mechanism(fuel)
    lhv = mech.heat_of_reaction_j_per_mol_fuel / mech.species[mech.fuel_index].molecular_weight
    assert lhv / 1.0e6 == pytest.approx(expected_lhv_mj_per_kg, rel=0.02)
    # The C2H4 preset LHV (50.4 MJ/kg) differs from the hf-derived value
    # (~47.16 MJ/kg); this is tracked as a data-consistency item (R8/R9).
    preset_lhv = {
        "CH4": 50.0, "C2H4": 50.4, "C3H8": 46.35, "H2": 120.0
    }[fuel]
    assert lhv / 1.0e6 == pytest.approx(preset_lhv, rel=0.08)


def test_cp_and_sensible_enthalpy_are_physical():
    species = load_species()
    assert species["CH4"].cp_mass(300.0) == pytest.approx(2229.0, rel=0.03)
    assert species["O2"].cp_mass(300.0) == pytest.approx(918.0, rel=0.03)
    assert species["N2"].cp_mass(300.0) == pytest.approx(1038.0, rel=0.03)
    assert species["CO2"].cp_mass(300.0) == pytest.approx(846.0, rel=0.03)
    assert species["H2O"].cp_mass(300.0) == pytest.approx(1865.0, rel=0.03)
    # Sensible enthalpy is zero at T_REF and positive above it.
    for rec in species.values():
        assert rec.hs_mass(T_REF) == pytest.approx(0.0, abs=1e-9)
        assert rec.hs_mass(500.0) > 0.0


def test_mixture_properties_and_eos():
    mech = Mechanism("CH4")
    Y = np.array([0.055, 0.220, 0.725, 0.0, 0.0])
    Y /= Y.sum()
    wmix = mech.molecular_weight(Y)
    assert wmix == pytest.approx(1.0 / np.sum(Y / mech.W), rel=1e-12)
    rho = mech.density(300.0, 101325.0, Y)
    assert rho == pytest.approx(101325.0 * wmix / (R_UNIV * 300.0), rel=1e-12)
    C = mech.concentrations(rho, Y)
    assert np.all(C >= 0.0)
    assert np.sum(C * mech.W) == pytest.approx(rho, rel=1e-12)


def test_reaction_rate_and_heat_release_shapes():
    mech = Mechanism("CH4")
    Y = np.array([0.055, 0.220, 0.725, 0.0, 0.0])
    Y /= Y.sum()
    rho = mech.density(2000.0, 101325.0, Y)
    xi = mech.reaction_rate_of_fuel(2000.0, rho, Y)
    omega = mech.production_rates(2000.0, rho, Y)
    qdot = mech.heat_release(2000.0, rho, Y)
    assert xi > 0.0
    assert omega[0] < 0.0  # fuel consumed
    assert omega[3] > 0.0 and omega[4] > 0.0  # CO2/H2O produced
    assert np.sum(omega * mech.W / mech.W) == pytest.approx(0.0, abs=1e-6)
    assert qdot > 0.0
    assert qdot == pytest.approx(-np.sum(mech.hf_mass * omega), rel=1e-12)


def test_custom_fuel_formula_builds_an_exothermic_reaction():
    preset = {
        "name": "Ethane",
        "formula": "C2H6",
        "pre_exponential_factor": 1e8,
        "activation_energy_j_per_mol": 1.3e5,
        "lower_heating_value_j_per_kg": 4.7e7,
        "specific_heat_j_per_kgK": 1900.0,
        "thermal_conductivity_w_per_mK": 0.028,
        "species_diffusivity_m2_per_s": 1.8e-5,
        "stoichiometric_fuel_o2_ratio": 0.2857,
        "adiabatic_flame_temp_k": 2250.0,
        "soot_tendency_index": 0.2,
        "max_laminar_flame_speed_m_per_s": 0.45,
        "reaction_order_fuel": 0.3,
        "reaction_order_oxygen": 1.2,
    }
    mech = Mechanism("C2H6", custom_fuel_preset=preset)
    assert mech.heat_of_reaction_j_per_mol_fuel > 0.0
    lhv = mech.heat_of_reaction_j_per_mol_fuel / mech.species[mech.fuel_index].molecular_weight
    assert lhv == pytest.approx(4.7e7, rel=0.05)
    assert mech.reaction.products == {"CO2": 2.0, "H2O": 3.0}


def test_mechanism_payload_is_json_safe_and_complete():
    mech = Mechanism("CH4")
    payload = mechanism_payload(mech)
    assert payload["species_keys"] == mech.species_keys
    assert len(payload["nu"]) == len(mech.species_keys)
    assert payload["reaction"]["key"] == "CH4_O2"
    assert payload["constants"]["R_univ"] == pytest.approx(R_UNIV)
    import json

    json.dumps(payload)  # must not raise
