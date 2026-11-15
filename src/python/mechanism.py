"""
Species / reaction mechanism layer for the 1D spherical solver.

The document's databases are used literally:

  species:  W_i, Cp_i(T), hf_i, lambda_i(T), mu_i(T), D_ij(T,p)
  reaction: reactants, products, nu', nu'', A, beta, Ea, orders

Built-in records live in src/shared/species_db.json and src/shared/reactions.json.
Optional user records are merged from data/custom_species.json and
data/custom_reactions.json (same shape as the built-ins).

This module deliberately contains only database, thermochemistry and unit
plumbing. The governing-equation discretization lives in solver1d/.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SHARED_DIR = Path(__file__).resolve().parent.parent / "shared"
DATA_DIR = REPO_ROOT / "data"
CUSTOM_SPECIES_PATH = DATA_DIR / "custom_species.json"
CUSTOM_REACTIONS_PATH = DATA_DIR / "custom_reactions.json"
CUSTOM_FUELS_PATH = DATA_DIR / "custom_fuels.json"

with open(SHARED_DIR / "constants.json", encoding="utf-8") as _fh:
    CONSTANTS = json.load(_fh)
R_UNIV = float(CONSTANTS["physical_constants"]["universal_gas_constant_j_per_molK"])
T_REF = float(CONSTANTS["physical_constants"]["reference_temperature_k"])
P_REF = float(CONSTANTS["physical_constants"]["atmosphere_pa"])
STANDARD_G = float(CONSTANTS["physical_constants"]["standard_gravity_m_per_s2"])

# Formula parser: element symbols + optional numeric count (integer or decimal).
_TOKEN_RE = re.compile(r"([A-Z][a-z]?)(\d*\.?\d*)")
_ALLOWED_ELEMENTS = {"C", "H", "O", "N"}


# ---------------------------------------------------------------------------
# Formula / stoichiometry helpers
# ---------------------------------------------------------------------------


def parse_formula(formula: str) -> Optional[dict[str, float]]:
    """Parse a simple C/H/O/N formula such as CH4, C2H4, C3H8, H2, C2H6O.

    Returns element -> count, or None if the string is not a simple formula
    with only C/H/O/N. Parentheses and hydrates are intentionally unsupported
    (recorded as a revision item for arbitrary user mechanisms).
    """
    if not formula or not isinstance(formula, str):
        return None
    pos = 0
    atoms: dict[str, float] = {}
    for match in _TOKEN_RE.finditer(formula):
        if match.start() != pos:
            return None
        element = match.group(1)
        count = match.group(2)
        if element not in _ALLOWED_ELEMENTS:
            return None
        n = float(count) if count else 1.0
        if n <= 0:
            return None
        atoms[element] = atoms.get(element, 0.0) + n
        pos = match.end()
    if pos != len(formula) or not atoms:
        return None
    return atoms


def formula_molecular_weight(atoms: dict[str, float]) -> Optional[float]:
    """kg/mol from a parsed formula using the species DB's atomic weights."""
    atomic = {"C": 0.012011, "H": 0.001008, "O": 0.015999, "N": 0.014007}
    try:
        return sum(atomic[el] * n for el, n in atoms.items())
    except KeyError:
        return None


def derive_stoichiometry(formula: str) -> Optional[dict[str, Any]]:
    """Derive a global single-step reaction from a hydrocarbon/oxygen formula.

    CxHyOz + (x + y/4 - z/2) O2 -> x CO2 + (y/2) H2O
    """
    atoms = parse_formula(formula)
    if atoms is None:
        return None
    x = atoms.get("C", 0.0)
    y = atoms.get("H", 0.0)
    z = atoms.get("O", 0.0)
    if x <= 0.0 and y <= 0.0:
        return None
    o2 = x + y / 4.0 - z / 2.0
    if o2 <= 0.0:
        return None
    products: dict[str, float] = {}
    if x > 0.0:
        products["CO2"] = x
    if y > 0.0:
        products["H2O"] = y / 2.0
    return {
        "reactants": {"__fuel__": 1.0, "O2": float(o2)},
        "products": products,
        "o2_per_fuel_mol": float(o2),
        "atoms": atoms,
    }


def _atomic_counts(species_key: str, species: dict[str, "Species"], side: dict[str, float]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for key, coeff in side.items():
        rec = species[key]
        atoms = parse_formula(rec.formula)
        if atoms is None:
            raise ValueError(f"cannot element-balance species {key!r} with formula {rec.formula!r}")
        for el, n in atoms.items():
            totals[el] = totals.get(el, 0.0) + n * coeff
    return totals


# ---------------------------------------------------------------------------
# Database records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Species:
    key: str
    name: str
    formula: str
    molecular_weight: float  # kg/mol
    heat_of_formation: float  # J/mol
    cp_model: str
    nasa7: Optional[dict[str, Any]] = None
    cp_constant: Optional[float] = None  # J/(kg K)
    k_ref: float = 0.026
    k_t_ref: float = 300.0
    k_exponent: float = 0.7
    mu_ref: float = 1.8e-5
    mu_t_ref: float = 300.0
    mu_exponent: float = 0.7
    d_ref: float = 2.0e-5
    d_t_ref: float = 300.0
    d_exponent: float = 1.75
    source: str = "built-in"

    # -- thermo -----------------------------------------------------------
    def _thermo_arrays(self, temperature):
        """Return (T_array>=1, NASA-7 coefficient array shape (N,7))."""
        assert self.nasa7 is not None
        t = np.atleast_1d(np.asarray(temperature, dtype=np.float64))
        t = np.maximum(t, 1.0)
        low = np.asarray(self.nasa7["low"], dtype=np.float64)
        high = np.asarray(self.nasa7["high"], dtype=np.float64)
        a = np.where((t <= float(self.nasa7["t_mid"]))[:, None], low[None, :], high[None, :])
        return t, a

    @staticmethod
    def _restore(value, original):
        arr = np.asarray(value, dtype=np.float64)
        if np.ndim(original) == 0:
            return float(arr.reshape(-1)[0])
        return arr.reshape(np.shape(original))

    def cp_molar(self, temperature):
        """J/(mol K). Accepts scalars or arrays."""
        if self.cp_model == "nasa7" and self.nasa7 is not None:
            t, a = self._thermo_arrays(temperature)
            val = R_UNIV * (a[:, 0] + a[:, 1] * t + a[:, 2] * t**2 + a[:, 3] * t**3 + a[:, 4] * t**4)
            return self._restore(val, temperature)
        if self.cp_constant is not None:
            t = np.atleast_1d(np.asarray(temperature, dtype=np.float64))
            return self._restore(np.full_like(t, self.cp_constant * self.molecular_weight), temperature)
        raise ValueError(f"species {self.key!r} has no Cp model")

    def cp_mass(self, temperature):
        """J/(kg K). Accepts scalars or arrays."""
        if self.cp_model == "nasa7" and self.nasa7 is not None:
            return self.cp_molar(temperature) / self.molecular_weight
        if self.cp_constant is not None:
            t = np.atleast_1d(np.asarray(temperature, dtype=np.float64))
            return self._restore(np.full_like(t, float(self.cp_constant)), temperature)
        raise ValueError(f"species {self.key!r} has no Cp model")

    def _h_integral(self, t: np.ndarray, a: np.ndarray) -> np.ndarray:
        return R_UNIV * (
            a[:, 0] * t
            + a[:, 1] * t**2 / 2.0
            + a[:, 2] * t**3 / 3.0
            + a[:, 3] * t**4 / 4.0
            + a[:, 4] * t**5 / 5.0
            + a[:, 5]
        )

    def hs_molar(self, temperature):
        """Sensible enthalpy relative to T_REF, J/mol. Scalars or arrays."""
        if self.cp_model == "nasa7" and self.nasa7 is not None:
            t, a = self._thermo_arrays(temperature)
            _, a_ref = self._thermo_arrays(T_REF)
            val = self._h_integral(t, a) - self._h_integral(np.array([T_REF]), a_ref)[0]
            return self._restore(val, temperature)
        if self.cp_constant is not None:
            t = np.atleast_1d(np.asarray(temperature, dtype=np.float64))
            val = float(self.cp_constant) * self.molecular_weight * (t - T_REF)
            return self._restore(val, temperature)
        raise ValueError(f"species {self.key!r} has no enthalpy model")

    def hs_mass(self, temperature):
        """Sensible enthalpy relative to T_REF, J/kg. Scalars or arrays."""
        if self.cp_model == "nasa7" and self.nasa7 is not None:
            return self.hs_molar(temperature) / self.molecular_weight
        if self.cp_constant is not None:
            t = np.atleast_1d(np.asarray(temperature, dtype=np.float64))
            return self._restore(float(self.cp_constant) * (t - T_REF), temperature)
        raise ValueError(f"species {self.key!r} has no enthalpy model")

    def hf_mass(self) -> float:
        """Specific enthalpy of formation, J/kg."""
        return self.heat_of_formation / self.molecular_weight

    # -- transport --------------------------------------------------------
    def thermal_conductivity(self, temperature):
        t = np.maximum(np.asarray(temperature, dtype=np.float64), 1.0)
        return self.k_ref * (t / self.k_t_ref) ** self.k_exponent

    def viscosity(self, temperature):
        t = np.maximum(np.asarray(temperature, dtype=np.float64), 1.0)
        return self.mu_ref * (t / self.mu_t_ref) ** self.mu_exponent

    def diffusivity(self, temperature, pressure_pa):
        """Reduced mixture-averaged reference diffusivity, m^2/s."""
        t = np.maximum(np.asarray(temperature, dtype=np.float64), 1.0)
        p = max(float(pressure_pa), 1.0)
        return self.d_ref * (t / self.d_t_ref) ** self.d_exponent * (P_REF / p)


@dataclass(frozen=True)
class Reaction:
    key: str
    fuel: str
    oxidizer: str
    reactants: dict[str, float]
    products: dict[str, float]
    orders: dict[str, float]
    pre_exponential_factor: float
    temperature_exponent: float
    activation_energy: float
    rate_units: str
    concentration_units: str
    source: str = "built-in"

    @property
    def all_species(self) -> list[str]:
        keys = list(self.reactants) + [k for k in self.products if k not in self.reactants]
        return keys

    @property
    def order_sum(self) -> float:
        return float(sum(self.orders.values()))


# ---------------------------------------------------------------------------
# Loading / validation
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _species_from_record(key: str, record: dict[str, Any], source: str) -> Species:
    nasa7 = record.get("nasa7")
    cp_model = record.get("cp_model", "nasa7" if nasa7 else "constant")
    cp_constant = record.get("cp_j_per_kgk")
    if cp_model == "constant" and cp_constant is None:
        cp_constant = record.get("specific_heat_j_per_kgK")
    k = record.get("thermal_conductivity", {})
    mu = record.get("viscosity", {})
    d = record.get("diffusivity", {})
    return Species(
        key=key,
        name=str(record.get("name", key)),
        formula=str(record.get("formula", key)),
        molecular_weight=float(record["molecular_weight_kg_per_mol"]),
        heat_of_formation=float(record.get("heat_of_formation_j_per_mol", 0.0)),
        cp_model=cp_model,
        nasa7=nasa7,
        cp_constant=float(cp_constant) if cp_constant is not None else None,
        k_ref=float(k.get("ref_w_per_mk", record.get("thermal_conductivity_w_per_mK", 0.026))),
        k_t_ref=float(k.get("t_ref_k", 300.0)),
        k_exponent=float(k.get("exponent", 0.7)),
        mu_ref=float(mu.get("ref_pa_s", record.get("viscosity_pa_s", 1.8e-5))),
        mu_t_ref=float(mu.get("t_ref_k", 300.0)),
        mu_exponent=float(mu.get("exponent", 0.7)),
        d_ref=float(d.get("ref_m2_per_s", record.get("species_diffusivity_m2_per_s", 2.0e-5))),
        d_t_ref=float(d.get("t_ref_k", 300.0)),
        d_exponent=float(d.get("exponent", 1.75)),
        source=source,
    )


def load_species() -> dict[str, Species]:
    """Built-in species merged with optional custom species."""
    with open(SHARED_DIR / "species_db.json", encoding="utf-8") as fh:
        raw = json.load(fh)
    species: dict[str, Species] = {}
    for key, rec in raw.get("species", {}).items():
        species[key] = _species_from_record(key, rec, "built-in")
    for key, rec in _load_json(CUSTOM_SPECIES_PATH).items():
        try:
            species[key] = _species_from_record(key, rec, "custom")
        except (KeyError, TypeError, ValueError):
            continue
    return species


def load_reactions() -> dict[str, Reaction]:
    """Built-in reactions merged with optional custom reactions."""
    with open(SHARED_DIR / "reactions.json", encoding="utf-8") as fh:
        raw = json.load(fh)
    reactions: dict[str, Reaction] = {}
    for key, rec in raw.get("reactions", {}).items():
        reactions[key] = Reaction(
            key=key,
            fuel=str(rec["fuel"]),
            oxidizer=str(rec.get("oxidizer", "O2")),
            reactants={str(k): float(v) for k, v in rec["reactants"].items()},
            products={str(k): float(v) for k, v in rec["products"].items()},
            orders={str(k): float(v) for k, v in rec.get("orders", {}).items()},
            pre_exponential_factor=float(rec["pre_exponential_factor"]),
            temperature_exponent=float(rec.get("temperature_exponent", 0.0)),
            activation_energy=float(rec["activation_energy_j_per_mol"]),
            rate_units=str(rec.get("rate_units", "")),
            concentration_units=str(rec.get("concentration_units", "mol/m^3")),
            source=str(rec.get("source", "built-in")),
        )
    for key, rec in _load_json(CUSTOM_REACTIONS_PATH).items():
        try:
            reactions[key] = Reaction(
                key=key,
                fuel=str(rec["fuel"]),
                oxidizer=str(rec.get("oxidizer", "O2")),
                reactants={str(k): float(v) for k, v in rec["reactants"].items()},
                products={str(k): float(v) for k, v in rec["products"].items()},
                orders={str(k): float(v) for k, v in rec.get("orders", {}).items()},
                pre_exponential_factor=float(rec["pre_exponential_factor"]),
                temperature_exponent=float(rec.get("temperature_exponent", 0.0)),
                activation_energy=float(rec["activation_energy_j_per_mol"]),
                rate_units=str(rec.get("rate_units", "")),
                concentration_units=str(rec.get("concentration_units", "mol/m^3")),
                source="custom",
            )
        except (KeyError, TypeError, ValueError):
            continue
    return reactions


def validate_reaction(reaction: Reaction, species: dict[str, Species]) -> None:
    """Elemental balance + mass conservation + required unit metadata."""
    missing = [k for k in reaction.all_species if k not in species]
    if missing:
        raise ValueError(f"reaction {reaction.key!r} references unknown species {missing}")
    if not reaction.rate_units:
        raise ValueError(f"reaction {reaction.key!r} is missing rate_units")
    if reaction.pre_exponential_factor <= 0.0:
        raise ValueError(f"reaction {reaction.key!r} has non-positive A")
    if reaction.activation_energy < 0.0:
        raise ValueError(f"reaction {reaction.key!r} has negative Ea")
    if any(v < 0.0 for v in reaction.orders.values()):
        raise ValueError(f"reaction {reaction.key!r} has a negative reaction order")
    left = _atomic_counts(reaction.key, species, reaction.reactants)
    right = _atomic_counts(reaction.key, species, reaction.products)
    for element in sorted(set(left) | set(right)):
        if abs(left.get(element, 0.0) - right.get(element, 0.0)) > 1e-9:
            raise ValueError(
                f"reaction {reaction.key!r} is not element-balanced for {element}: "
                f"{left.get(element, 0.0)} vs {right.get(element, 0.0)}"
            )
    mass_left = sum(species[k].molecular_weight * v for k, v in reaction.reactants.items())
    mass_right = sum(species[k].molecular_weight * v for k, v in reaction.products.items())
    # Molecular weights in the DB are rounded to ~6 significant figures, so the
    # mass check uses a relative tolerance rather than exact equality.
    if abs(mass_left - mass_right) > 1e-4 * max(1.0, mass_left):
        raise ValueError(
            f"reaction {reaction.key!r} violates mass conservation: "
            f"{mass_left:.9g} vs {mass_right:.9g} kg/mol"
        )


def _derived_reaction_for_custom_fuel(
    fuel_key: str,
    preset: dict[str, Any],
    species: dict[str, Species],
) -> Optional[Reaction]:
    """Build a pseudo-species + global reaction for a custom fuel preset.

    Custom presets carry formula, LHV, cp, transport and kinetic fields but not
    molecular weight or hf. We derive W from the formula (fallback 0.03 kg/mol)
    and choose hf so the heat of reaction reproduces the preset LHV.
    """
    formula = str(preset.get("formula") or fuel_key)
    stoich = derive_stoichiometry(formula)
    if stoich is None:
        return None
    W = formula_molecular_weight(stoich["atoms"]) or 0.03
    # Products' formation enthalpies fix the fuel hf that reproduces the LHV.
    product_hf = sum(
        species[key].heat_of_formation * coeff
        for key, coeff in stoich["products"].items()
        if key in species
    )
    lhv = float(preset.get("lower_heating_value_j_per_kg", 5.0e7))
    # ΔH = products − fuel; for an exothermic LHV, hf_fuel = products + LHV·W.
    hf_fuel = product_hf + lhv * W
    pseudo = Species(
        key=fuel_key,
        name=str(preset.get("name", fuel_key)),
        formula=formula,
        molecular_weight=W,
        heat_of_formation=hf_fuel,
        cp_model="constant",
        cp_constant=float(preset.get("specific_heat_j_per_kgK", 2000.0)),
        k_ref=float(preset.get("thermal_conductivity_w_per_mK", 0.03)),
        mu_ref=float(preset.get("viscosity_pa_s", 1.5e-5)),
        d_ref=float(preset.get("species_diffusivity_m2_per_s", 2.0e-5)),
        source="custom-fuel",
    )
    species[fuel_key] = pseudo
    reactants = {fuel_key: 1.0, "O2": stoich["o2_per_fuel_mol"]}
    reaction = Reaction(
        key=f"{fuel_key}_O2",
        fuel=fuel_key,
        oxidizer="O2",
        reactants=reactants,
        products=dict(stoich["products"]),
        orders={
            fuel_key: float(preset.get("reaction_order_fuel", 0.5)),
            "O2": float(preset.get("reaction_order_oxygen", 1.0)),
        },
        pre_exponential_factor=float(preset.get("pre_exponential_factor", 1.0e8)),
        temperature_exponent=float(preset.get("temperature_exponent", 0.0)),
        activation_energy=float(preset.get("activation_energy_j_per_mol", 1.2e5)),
        rate_units="mol^(1 - sum(orders)) * m^(3*(sum(orders) - 1)) * s^-1",
        concentration_units="mol/m^3",
        source="custom-fuel-derived",
    )
    return reaction


# ---------------------------------------------------------------------------
# Mechanism (species subset + reaction arrays used by the solver)
# ---------------------------------------------------------------------------


class Mechanism:
    """Resolved species/reaction set for one fuel + oxidizer selection."""

    def __init__(
        self,
        fuel: str,
        oxidizer: str = "air",
        reaction_key: Optional[str] = None,
        custom_fuel_preset: Optional[dict[str, Any]] = None,
    ) -> None:
        self.species_db = load_species()
        self.reactions_db = load_reactions()
        self.fuel = fuel
        self.oxidizer_mode = oxidizer

        key = reaction_key or f"{fuel}_O2"
        if key in self.reactions_db:
            reaction = self.reactions_db[key]
        elif custom_fuel_preset is not None:
            reaction = _derived_reaction_for_custom_fuel(fuel, custom_fuel_preset, self.species_db)
            if reaction is None:
                raise ValueError(
                    f"custom fuel {fuel!r} formula {custom_fuel_preset.get('formula')!r} "
                    "cannot be converted to a C/H/O reaction"
                )
        else:
            raise ValueError(f"no reaction {key!r} for fuel {fuel!r}")

        validate_reaction(reaction, self.species_db)

        # The solver state contains the reaction participants plus N2 as the
        # inert bath gas (and O2 even when it is not a reactant, for oxidizer
        # boundary conditions).
        ordered: list[str] = []
        for candidate in [fuel, "O2", "N2"] + list(reaction.products):
            if candidate in self.species_db and candidate not in ordered:
                ordered.append(candidate)
        for candidate in reaction.reactants:
            if candidate not in ordered:
                ordered.append(candidate)
        self.species_keys = ordered
        self.species = [self.species_db[k] for k in ordered]
        self.key_to_index = {k: i for i, k in enumerate(ordered)}
        self.reaction = reaction

        n = len(ordered)
        self.nu = np.zeros(n, dtype=np.float64)
        self.orders = np.zeros(n, dtype=np.float64)
        for k, v in reaction.reactants.items():
            self.nu[self.key_to_index[k]] -= float(v)
        for k, v in reaction.products.items():
            self.nu[self.key_to_index[k]] += float(v)
        for k, v in reaction.orders.items():
            if k in self.key_to_index:
                self.orders[self.key_to_index[k]] = float(v)

        self.W = np.array([s.molecular_weight for s in self.species], dtype=np.float64)
        self.hf = np.array([s.heat_of_formation for s in self.species], dtype=np.float64)
        self.hf_mass = self.hf / self.W
        # ΔH per mole of fuel reacted (negative for exothermic).
        self.heat_of_reaction_j_per_mol_fuel = float(-np.dot(self.nu, self.hf))
        self.fuel_index = self.key_to_index[fuel]
        self.o2_index = self.key_to_index.get("O2")
        self.n2_index = self.key_to_index.get("N2")

    # -- mixture properties ------------------------------------------------
    def molecular_weight(self, Y: np.ndarray) -> np.ndarray:
        """W_mix = [Σ Y_i/W_i]^-1, kg/mol."""
        inv = np.sum(Y / self.W, axis=-1)
        return 1.0 / np.maximum(inv, 1e-30)

    def density(self, temperature: np.ndarray, pressure_pa: float, Y: np.ndarray) -> np.ndarray:
        """ρ = p0 W_mix / (R_u T), kg/m³."""
        return pressure_pa * self.molecular_weight(Y) / (R_UNIV * np.maximum(temperature, 1.0))

    def concentrations(self, rho: np.ndarray, Y: np.ndarray) -> np.ndarray:
        """C_i = ρ Y_i / W_i, mol/m³."""
        r = np.asarray(rho, dtype=np.float64)
        if r.ndim == 0:
            return float(r) * Y / self.W
        return r[..., np.newaxis] * Y / self.W

    def cp_mix(self, temperature: np.ndarray, Y: np.ndarray) -> np.ndarray:
        """Mass-weighted mixture cp, J/(kg K)."""
        cp = np.stack([s.cp_mass(temperature) for s in self.species], axis=-1)
        return np.sum(Y * cp, axis=-1)

    def hs_mix(self, temperature: np.ndarray, Y: np.ndarray) -> np.ndarray:
        """Mixture sensible enthalpy, J/kg."""
        hs = np.stack([s.hs_mass(temperature) for s in self.species], axis=-1)
        return np.sum(Y * hs, axis=-1)

    def temperature_from_hs(self, hs_target: np.ndarray, Y: np.ndarray, t_guess: np.ndarray) -> np.ndarray:
        """Invert h_s(T, Y) with a bounded Newton iteration."""
        t = np.clip(np.asarray(t_guess, dtype=np.float64), 200.0, 6000.0)
        target = np.asarray(hs_target, dtype=np.float64)
        for _ in range(24):
            f = self.hs_mix(t, Y) - target
            cp = np.maximum(self.cp_mix(t, Y), 1.0)
            step = f / cp
            t_new = np.clip(t - step, 200.0, 6000.0)
            if np.max(np.abs(t_new - t)) < 1e-6:
                t = t_new
                break
            t = t_new
        return t

    def lambda_mix(self, temperature: np.ndarray, Y: np.ndarray) -> np.ndarray:
        """Mass-weighted mixture conductivity (reduced model; see R8)."""
        k = np.stack([s.thermal_conductivity(temperature) for s in self.species], axis=-1)
        return np.sum(Y * k, axis=-1)

    def viscosity_mix(self, temperature: np.ndarray, Y: np.ndarray) -> np.ndarray:
        mu = np.stack([s.viscosity(temperature) for s in self.species], axis=-1)
        return np.sum(Y * mu, axis=-1)

    def diffusivity(self, temperature: np.ndarray, pressure_pa: float) -> np.ndarray:
        """Per-species reduced D_i,m, shape (..., n_species), m²/s."""
        vals = [s.diffusivity(temperature, pressure_pa) for s in self.species]
        return np.stack(vals, axis=-1)

    # -- chemistry ---------------------------------------------------------
    def rate_of_progress(self, temperature: np.ndarray, concentrations: np.ndarray) -> np.ndarray:
        """ξ̇ = A T^β exp(-Ea/(R T)) Π C_i^α_i, mol/(m³ s)."""
        t = np.maximum(np.asarray(temperature, dtype=np.float64), 200.0)
        r = self.reaction
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            arrhenius = r.pre_exponential_factor * t ** r.temperature_exponent * np.exp(
                -r.activation_energy / (R_UNIV * t)
            )
            product = np.ones_like(t, dtype=np.float64)
            for idx, order in enumerate(self.orders):
                if order > 0.0:
                    product *= np.maximum(concentrations[..., idx], 0.0) ** order
            value = arrhenius * product
        return np.nan_to_num(value, nan=0.0, posinf=1e30, neginf=0.0)

    def production_rates(self, temperature: np.ndarray, rho: np.ndarray, Y: np.ndarray) -> np.ndarray:
        """ω̇_i = W_i ν_i ξ̇, kg/(m³ s)."""
        c = self.concentrations(rho, Y)
        xi = self.rate_of_progress(temperature, c)
        if np.ndim(xi) == 0:
            return self.W * self.nu * float(xi)
        return self.W * self.nu * xi[..., np.newaxis]

    def heat_release(self, temperature: np.ndarray, rho: np.ndarray, Y: np.ndarray) -> np.ndarray:
        """q̇ = -Σ (hf_i/W_i) ω̇_i, W/m³ (see R5 for the unit interpretation)."""
        omega = self.production_rates(temperature, rho, Y)
        return -np.sum(self.hf_mass * omega, axis=-1)

    def reaction_rate_of_fuel(self, temperature: np.ndarray, rho: np.ndarray, Y: np.ndarray) -> np.ndarray:
        c = self.concentrations(rho, Y)
        return self.rate_of_progress(temperature, c)


def mechanism_for_config(cfg: Any) -> Mechanism:
    """Build a Mechanism from a SimConfig-like object (duck-typed)."""
    custom_preset = None
    if cfg.fuel not in ("CH4", "C2H4", "C3H8", "H2"):
        from fuel_db import list_presets  # local import avoids a cycle

        custom_preset = list_presets().get(cfg.fuel)
    return Mechanism(
        fuel=cfg.fuel,
        oxidizer=getattr(cfg, "oxidizer", "air"),
        reaction_key=getattr(cfg, "reaction", None),
        custom_fuel_preset=custom_preset,
    )


def fuel_soot_tendency(fuel: str) -> float:
    """Preset soot tendency (kept for the existing UI/Jev phenomenological score)."""
    try:
        with open(SHARED_DIR / "species_db.json", encoding="utf-8") as fh:
            fuels = json.load(fh).get("fuels", {})
        if fuel in fuels:
            return float(fuels[fuel].get("soot_tendency_index", 0.1))
    except (OSError, json.JSONDecodeError):
        pass
    custom = _load_json(CUSTOM_FUELS_PATH)
    return float(custom.get(fuel, {}).get("soot_tendency_index", 0.1))


def mechanism_payload(mech: Mechanism) -> dict[str, Any]:
    """Plain-dict payload passed to the C++ pybind11 solver."""
    species_payload = []
    for s in mech.species:
        species_payload.append(
            {
                "key": s.key,
                "formula": s.formula,
                "molecular_weight": s.molecular_weight,
                "heat_of_formation": s.heat_of_formation,
                "cp_model": s.cp_model,
                "nasa7": s.nasa7,
                "cp_constant": s.cp_constant,
                "thermal_conductivity": {
                    "ref": s.k_ref,
                    "t_ref": s.k_t_ref,
                    "exponent": s.k_exponent,
                },
                "viscosity": {
                    "ref": s.mu_ref,
                    "t_ref": s.mu_t_ref,
                    "exponent": s.mu_exponent,
                },
                "diffusivity": {
                    "ref": s.d_ref,
                    "t_ref": s.d_t_ref,
                    "exponent": s.d_exponent,
                },
            }
        )
    r = mech.reaction
    return {
        "fuel": mech.fuel,
        "soot_tendency_index": fuel_soot_tendency(mech.fuel),
        "species": species_payload,
        "species_keys": list(mech.species_keys),
        "reaction": {
            "key": r.key,
            "fuel": r.fuel,
            "oxidizer": r.oxidizer,
            "reactants": dict(r.reactants),
            "products": dict(r.products),
            "orders": dict(r.orders),
            "pre_exponential_factor": r.pre_exponential_factor,
            "temperature_exponent": r.temperature_exponent,
            "activation_energy": r.activation_energy,
            "rate_units": r.rate_units,
            "concentration_units": r.concentration_units,
        },
        "nu": mech.nu.tolist(),
        "orders": mech.orders.tolist(),
        "fuel_index": mech.fuel_index,
        "o2_index": mech.o2_index,
        "n2_index": mech.n2_index,
        "heat_of_reaction_j_per_mol_fuel": mech.heat_of_reaction_j_per_mol_fuel,
        "constants": {"R_univ": R_UNIV, "T_ref": T_REF, "P_ref": P_REF},
    }


def mechanism_summary(mech: Mechanism) -> dict[str, Any]:
    """Compact serializable description for the UI / diagnostics."""
    return {
        "fuel": mech.fuel,
        "reaction": mech.reaction.key,
        "species": list(mech.species_keys),
        "stoichiometry": {
            "reactants": mech.reaction.reactants,
            "products": mech.reaction.products,
        },
        "orders": dict(zip(mech.species_keys, mech.orders.tolist())),
        "heat_of_reaction_j_per_mol_fuel": mech.heat_of_reaction_j_per_mol_fuel,
        "rate_units": mech.reaction.rate_units,
        "concentration_units": mech.reaction.concentration_units,
        "sources": {s.key: s.source for s in mech.species},
    }
