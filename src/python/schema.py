"""
Unified data schema for T.R.I.A.G.E.

Three representations of one reality, all sharing a compact JSON shape (<250 tokens):
  1. Live C++ engine runs        (via sim_bridge)
  2. Historical NASA PSI runs    (via s3_ingest)
  3. The unified payload sent to Jev triage (jev_client)

Solver seam contract (binding for the real pybind11 module, to be implemented in src/cpp/):
    triage_core.run_simulation(config: dict, mechanism: dict) -> dict
        config keys = SimConfig.model_dump() with "fuel" resolved to a preset key
        from species_db.json or a persisted custom preset (data/custom_fuels.json).
        mechanism = resolved species/reaction arrays from mechanism.mechanism_payload().
        The physics core is a 1D spherical radial finite-volume model
        (r_min_m..r_max_m, Nr cells) per Combustion_Solver_Architecture_English.docx.
        Returns:
            frames: list[list[list[float]]]  # painted T field, row-major [ny][nx], Kelvin
            times:  list[float]              # seconds, len == len(frames)
            history: list[dict]             # per-saved-step scalars:
                #   t_s, max_flame_radius_m, peak_temp_k, mean_temp_k,
                #   fuel_burned_fraction, soot_index, buoyancy_ke
            final: dict                       # scalars at t_end + radial/diagnostics:
                #   quenched, quench_time_s, peak_temp_k, max_flame_radius_m,
                #   soot_volume_fraction, stability, radial, diagnostics
            radial_frames: list[dict]         # optional coarse radial snapshots

sim_bridge tries `import triage_core` and falls back to the NumPy reference
implementation in src/python/solver1d/. All downstream code only ever talks to
SimResult / SimConfig — never the .so directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

SHARED_DIR = Path(__file__).resolve().parent.parent / "shared"
CUSTOM_FUELS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "custom_fuels.json"
FUELS = ("CH4", "C2H4", "C3H8", "H2")
GravityMode = Literal["zero_g", "iss_micro_g", "earth_1g", "mars_g", "moon_g", "custom"]
IgnitionMethod = Literal["hot_spot", "energy_deposition"]


def custom_fuel_keys() -> tuple[str, ...]:
    """Persisted custom preset keys (data/custom_fuels.json), sorted."""
    if not CUSTOM_FUELS_PATH.exists():
        return ()
    try:
        return tuple(sorted(json.loads(CUSTOM_FUELS_PATH.read_text(encoding="utf-8")).keys()))
    except (json.JSONDecodeError, OSError):
        return ()


def load_json(name: str) -> dict[str, Any]:
    with open(SHARED_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


SPECIES_DB: dict[str, Any] = load_json("species_db.json")
CONSTANTS: dict[str, Any] = load_json("constants.json")


class SimConfig(BaseModel):
    """Boundary conditions + grid. One source of truth for UI, C++, and cache keys."""

    # --- Primary (always-visible) controls ---
    fuel: str = Field("CH4", description=f"Fuel preset key: {FUELS}")
    oxygen_pct: float = Field(21.0, ge=1.0, le=100.0)
    ambient_pressure_bar: float = Field(1.0, ge=0.1, le=10.0)
    ambient_temperature_k: float = Field(300.0, ge=200.0, le=500.0)
    gravity_mode: GravityMode = "zero_g"
    custom_gravity_m_per_s2: float = Field(3.7, ge=0.0, le=50.0, description="g magnitude when gravity_mode == 'custom'")
    custom_g_jitter_m_per_s2: float = Field(0.0, ge=0.0, le=1.0)
    inlet_velocity_ms: float = Field(0.0, ge=0.0, le=2.0)
    ignition_method: IgnitionMethod = "energy_deposition"
    ignition_energy_j: float = Field(2.0, ge=0.01, le=100.0)

    # --- 1D spherical solver (document architecture) ---
    geometry: Literal["spherical_1d"] = "spherical_1d"
    r_min_m: float = Field(0.001, ge=0.0, description="Inner radial boundary (m)")
    r_max_m: float = Field(0.04, gt=0.0, description="Outer radial boundary (m)")
    Nr: int = Field(256, ge=16, le=2048, description="Radial solver cells")
    mass_flow_kg_s: float = Field(0.0, ge=0.0, le=1.0, description="Inlet mass flow rate (kg/s)")
    radial_gravity_m_per_s2: Optional[float] = Field(
        None, ge=-50.0, le=50.0, description="Effective radial g_r; defaults from gravity_mode"
    )
    t_end_s: Optional[float] = Field(None, gt=0.0, description="Simulation end time; derives iteration_count")
    mixing_mode: Literal["premixed", "nonpremixed"] = "premixed"
    equivalence_ratio: float = Field(1.0, ge=0.2, le=5.0)
    oxidizer: Literal["air", "O2"] = "air"
    reaction: Optional[str] = Field(None, description="Reaction key; defaults to <fuel>_O2")
    initial_species_mass_fractions: Optional[dict[str, float]] = None
    fuel_inlet_composition: Optional[dict[str, float]] = None
    oxidizer_inlet_composition: Optional[dict[str, float]] = None
    inlet_temperature_k: Optional[float] = Field(None, ge=200.0, le=2000.0)
    inner_bc: Literal["fixed", "zero_gradient"] = "fixed"
    outer_bc: Literal["fixed", "zero_gradient"] = "fixed"

    # --- Advanced (collapsed accordion) ---
    nx: int = Field(128, ge=16, le=512)
    ny: int = Field(128, ge=16, le=512)
    dt_s: float = Field(1e-3, gt=0.0, le=1.0, description="Solver step size (s); run length is set by iteration_count x dt")
    iteration_count: int = Field(200, ge=1, le=20000, description="Number of solver steps to run")
    pre_exponential_override: Optional[float] = Field(None, description="Arrhenius A override")
    activation_energy_override: Optional[float] = Field(None, description="Arrhenius Ea override")
    domain_length_m: float = Field(0.08, gt=0.0)
    domain_height_m: float = Field(0.08, gt=0.0)
    ignition_region_m: float = Field(3e-3, gt=0.0)
    output_interval_steps: int = Field(4, ge=1, le=64)

    # --- Resolved from databases (never user-entered) ---
    source: str = Field("sim", description="Provenance: sim | psi")
    experiment_id: Optional[str] = Field(None, description="PSI run id when source == psi")

    @field_validator("fuel")
    @classmethod
    def _fuel_in_db(cls, v: str) -> str:
        if v not in FUELS + custom_fuel_keys():
            raise ValueError(f"fuel must be a preset key (built-in or custom), got {v!r}")
        return v

    def resolved_chemistry(self) -> dict[str, float]:
        """Merge the species_db/custom preset with any Arrhenius overrides."""
        if self.fuel in FUELS:
            preset = SPECIES_DB["fuels"][self.fuel]
        else:
            from fuel_db import list_presets  # local module, avoids import cycle at load

            preset = list_presets()[self.fuel]
        chem = {k: float(v) for k, v in preset.items() if isinstance(v, (int, float)) and k != "stoichiometric_fuel_o2_ratio"}
        chem["stoich_fuel_o2"] = float(preset["stoichiometric_fuel_o2_ratio"])
        if self.pre_exponential_override is not None:
            chem["pre_exponential_factor"] = self.pre_exponential_override
        if self.activation_energy_override is not None:
            chem["activation_energy_j_per_mol"] = self.activation_energy_override
        return chem

    def gravity(self) -> tuple[float, float]:
        """(magnitude, jitter) in m/s^2 for the selected gravity mode."""
        if self.gravity_mode == "custom":
            return float(self.custom_gravity_m_per_s2), float(self.custom_g_jitter_m_per_s2)
        gm = CONSTANTS["gravity_modes"][self.gravity_mode]
        return float(gm["g_m_per_s2"]), float(gm["g_jitter_m_per_s2"])

    def radial_gravity(self) -> float:
        """Effective radial g_r (m/s^2), outward-positive convention.

        The document leaves the sign/definition to the user; we map gravity
        inward (negative outward) so momentum residual R2 is physically
        interpretable. An explicit radial_gravity_m_per_s2 overrides this.
        """
        if self.radial_gravity_m_per_s2 is not None:
            return float(self.radial_gravity_m_per_s2)
        return -float(self.gravity()[0])

    def run_end_time_s(self) -> float:
        """Run length in seconds (iteration_count x dt_s)."""
        return float(self.iteration_count) * float(self.dt_s)

    def resolved_mechanism(self):
        """Resolve the species/reaction mechanism for this config."""
        from mechanism import mechanism_for_config

        return mechanism_for_config(self)

    @field_validator(
        "initial_species_mass_fractions",
        "fuel_inlet_composition",
        "oxidizer_inlet_composition",
    )
    @classmethod
    def _mass_fraction_maps(cls, v: Optional[dict[str, float]]):
        if v is None:
            return v
        clean = {str(k): float(val) for k, val in v.items()}
        if any(val < 0.0 for val in clean.values()):
            raise ValueError("mass fractions must be non-negative")
        if sum(clean.values()) > 1.0001:
            raise ValueError("mass fractions must sum to <= 1 (N2 fills the balance)")
        return clean

    @model_validator(mode="after")
    def _check_spherical_domain(self):
        if self.r_max_m <= self.r_min_m:
            raise ValueError("r_max_m must be greater than r_min_m")
        if self.mass_flow_kg_s > 0.0 and self.r_min_m <= 0.0:
            raise ValueError("mass_flow_kg_s > 0 requires r_min_m > 0 (1/r^2 singularity)")
        if self.t_end_s is not None:
            # t_end is authoritative when supplied; keep iteration_count in sync
            # so the rest of the backend/UI contract (iteration_count x dt_s)
            # remains exact.
            self.iteration_count = max(1, int(round(float(self.t_end_s) / float(self.dt_s))))
        return self

    def cache_key(self) -> str:
        """Stable short hash for parameter-sweep dedup + result caching."""
        import hashlib

        blob = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


class UnifiedPayload(BaseModel):
    """Compact (<250 token) run descriptor — identical shape for PSI history and sim runs."""

    source: Literal["sim", "psi"] = "sim"
    fuel: str
    oxygen_pct: float
    ambient_pressure_bar: float
    gravity_mode: GravityMode
    inlet_velocity_ms: float = 0.0
    ignition_energy: Optional[float] = None
    experiment_id: Optional[str] = Field(
        None, description="PSI experiment id, when available (used by tier-1 profile matching)"
    )

    # Telemetry summary
    max_radius_mm: Optional[float] = None
    quench_time_s: Optional[float] = None
    peak_temp_k: Optional[float] = None
    soot_yield_index: Optional[float] = None
    stability: Optional[float] = None
    profile_r: list[float] = Field(default_factory=list, description="Downsampled radial/slice profile")
    profile_t: list[float] = Field(default_factory=list, description="Downsampled temperature history")

    @field_validator("fuel")
    @classmethod
    def _fuel_ok(cls, v: str) -> str:
        if v not in FUELS + custom_fuel_keys():
            raise ValueError(
                f"fuel must be a preset key (built-in or custom), got {v!r}"
            )
        return v


class JevVerdict(BaseModel):
    """Tier-1 structured triage output from typesafe/jev-latest (schema enforced by NanoGPT)."""

    flame_morphology: Literal["spherical", "teardrop", "fragmented", "extinguished"]
    buoyancy_driven_convection: bool
    nasa_experiment_profile_match: Literal["ACME", "SOFIE", "FLEX", "NONE"]
    soot_volume_fraction_score: float = Field(ge=0.0, le=100.0)
    radiant_heat_loss_critical: bool
    stability_score: float = Field(ge=0.0, le=100.0)
    delta_score: float = Field(ge=0.0, le=100.0, description="sim-vs-PSI disagreement")
    confidence_score: float = Field(ge=0.0, le=1.0)
    notes: str = Field("", max_length=280)

    @property
    def should_refine(self) -> bool:
        """High delta or low stability triggers fine-grained C++ sweeps around quench boundaries."""
        return self.delta_score > 60.0 or self.stability_score < 40.0


class SimResult(BaseModel):
    """Normalization layer over whatever the solver seam returns."""

    config: SimConfig
    frames: list[list[list[float]]] = Field(description="Painted T field [ny][nx], Kelvin")
    times: list[float]
    history: list[dict[str, Any]]
    final: dict[str, Any]
    radial_frames: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Coarse 1D radial snapshots (r, T, species, qdot) per saved step",
    )
    solver: str = Field(description="'triage_core' (C++) or 'reference' (NumPy 1D)")

    def to_unified(self) -> UnifiedPayload:
        gm, _ = self.config.gravity()
        return UnifiedPayload(
            source="sim",
            fuel=self.config.fuel,
            oxygen_pct=self.config.oxygen_pct,
            ambient_pressure_bar=self.config.ambient_pressure_bar,
            gravity_mode=self.config.gravity_mode,
            inlet_velocity_ms=self.config.inlet_velocity_ms,
            ignition_energy=self.config.ignition_energy_j,
            experiment_id=self.config.experiment_id,
            max_radius_mm=(self.final.get("max_flame_radius_m") or 0.0) * 1000.0,
            quench_time_s=self.final.get("quench_time_s"),
            peak_temp_k=self.final.get("peak_temp_k"),
            soot_yield_index=self.final.get("soot_volume_fraction"),
            stability=self.final.get("stability"),
            profile_r=_downsample(self.history, "max_flame_radius_m", 24),
            profile_t=_downsample(self.history, "peak_temp_k", 24),
        )


def _downsample(history: list[dict[str, Any]], key: str, n: int) -> list[float]:
    vals = [float(h[key]) for h in history if key in h]
    if not vals:
        return []
    if len(vals) <= n:
        return [round(v, 4) for v in vals]
    step = (len(vals) - 1) / (n - 1)
    return [round(vals[int(i * step)], 4) for i in range(n)]


# --- Client-facing WebSocket message envelopes ---

class WsInbound(BaseModel):
    kind: Literal["config", "sweep", "triage_request", "tier2_request", "ping"]


class WsOutbound(BaseModel):
    kind: Literal["sim_result", "sweep_result", "triage", "tier2_report", "error", "pong"]