"""
Custom fuel preset store — user-defined presets persisted to data/custom_fuels.json.

Built-in presets live in src/shared/species_db.json and are read-only; anything
saved here is merged on top at list time, so the rest of the pipeline (schema,
solver, triage) sees one uniform preset table. Keys are uppercase identifiers;
built-in keys are reserved and cannot be overwritten.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SHARED_DIR = Path(__file__).resolve().parent.parent / "shared"
CUSTOM_PATH = REPO_ROOT / "data" / "custom_fuels.json"

BUILTIN_KEYS = ("CH4", "C2H4", "C3H8", "H2")

# Editable chemistry fields ("database variables") a custom preset carries,
# with validation ranges shared to the UI via the fuel_list message.
FUEL_FIELDS: dict[str, tuple[float, float]] = {
    "pre_exponential_factor": (1e5, 1e12),
    "activation_energy_j_per_mol": (3e4, 3e5),
    "lower_heating_value_j_per_kg": (1e7, 2e8),
    "specific_heat_j_per_kgK": (800.0, 20000.0),
    "thermal_conductivity_w_per_mK": (0.005, 0.5),
    "species_diffusivity_m2_per_s": (5e-6, 2e-4),
    "stoichiometric_fuel_o2_ratio": (0.05, 4.0),
    "adiabatic_flame_temp_k": (1200.0, 3200.0),
    "soot_tendency_index": (0.0, 1.0),
    "max_laminar_flame_speed_m_per_s": (0.05, 4.0),
    "reaction_order_fuel": (0.0, 1.5),
    "reaction_order_oxygen": (0.0, 2.0),
}


def _builtin() -> dict[str, Any]:
    with open(SHARED_DIR / "species_db.json", encoding="utf-8") as fh:
        return json.load(fh)["fuels"]


def _load_custom() -> dict[str, Any]:
    if not CUSTOM_PATH.exists():
        return {}
    return json.loads(CUSTOM_PATH.read_text(encoding="utf-8"))


def _save_custom(fuels: dict[str, Any]) -> None:
    CUSTOM_PATH.parent.mkdir(parents=True, exist_ok=True)
    CUSTOM_PATH.write_text(json.dumps(fuels, indent=2, sort_keys=True), encoding="utf-8")


def list_presets() -> dict[str, dict[str, Any]]:
    """Merged read-only view: built-in species_db presets + persisted customs."""
    merged = {k: dict(v) for k, v in _builtin().items()}
    merged.update(_load_custom())
    return merged


def validate_custom(key: str, data: dict[str, Any]) -> dict[str, Any]:
    """Validate + normalize one custom preset. Raises ValueError on bad input."""
    key = (key or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_\-]{0,15}", key):
        raise ValueError(f"bad fuel key {key!r}: use up to 16 uppercase letters/digits")
    if key in BUILTIN_KEYS:
        raise ValueError(f"{key} is a built-in preset; pick another name")
    out: dict[str, Any] = {
        "name": str(data.get("name") or key).strip()[:40] or key,
        "formula": str(data.get("formula") or key).strip()[:12] or key,
    }
    for field, (lo, hi) in FUEL_FIELDS.items():
        try:
            v = float(data.get(field))
        except (TypeError, ValueError):
            raise ValueError(f"{field}: not a number") from None
        if not lo <= v <= hi:
            raise ValueError(f"{field}: {v} outside [{lo:g}, {hi:g}]")
        out[field] = v
    return {key: out}


def save_preset(key: str, data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Insert or update one custom preset (edit == same key). Returns the merged list."""
    custom = _load_custom()
    custom.update(validate_custom(key, data))
    _save_custom(custom)
    return list_presets()


def delete_preset(key: str) -> dict[str, dict[str, Any]]:
    """Remove one custom preset. Returns the merged list."""
    custom = _load_custom()
    if key not in custom:
        raise ValueError(f"no custom preset {key!r}")
    del custom[key]
    _save_custom(custom)
    return list_presets()