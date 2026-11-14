import React, { useState } from "react";

/**
 * Progressive-disclosure control panel.
 * Primary controls always visible; advanced numerical settings live in a
 * collapsed accordion; conditional fields appear per the inputs spec
 * (wall temperature only for isothermal walls, etc.).
 */
export default function ControlPanel({
  config,
  update,
  species,
  gravityModes,
  onRun,
  onSweep,
  busy,
}) {
  const [advancedOpen, setAdvancedOpen] = useState(false);

  return (
    <div className="panel control-panel">
      <h2>Digital Twin Controls</h2>

      <label className="field">
        <span>Fuel preset</span>
        <select
          value={config.fuel}
          onChange={(e) => update("fuel", e.target.value)}
        >
          {species.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
      </label>

      <Slider
        label="Oxygen %"
        value={config.oxygen_pct}
        min={1}
        max={100}
        step={0.5}
        onChange={(v) => update("oxygen_pct", v)}
        unit="%"
      />
      <Slider
        label="Ambient pressure"
        value={config.ambient_pressure_bar}
        min={0.1}
        max={10}
        step={0.1}
        onChange={(v) => update("ambient_pressure_bar", v)}
        unit="bar"
      />
      <Slider
        label="Ambient temperature"
        value={config.ambient_temperature_k}
        min={200}
        max={500}
        step={5}
        onChange={(v) => update("ambient_temperature_k", v)}
        unit="K"
      />

      <label className="field">
        <span>Gravity mode</span>
        <select
          value={config.gravity_mode}
          onChange={(e) => update("gravity_mode", e.target.value)}
        >
          {gravityModes.map((g) => (
            <option key={g.key} value={g.key}>
              {g.label}
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>Ignition method</span>
        <select
          value={config.ignition_method}
          onChange={(e) => update("ignition_method", e.target.value)}
        >
          <option value="energy_deposition">Energy deposition</option>
          <option value="hot_spot">Hot spot (prescribed T)</option>
        </select>
      </label>

      {config.ignition_method === "energy_deposition" ? (
        <Slider
          label="Ignition energy"
          value={config.ignition_energy_j}
          min={0.01}
          max={100}
          step={0.5}
          onChange={(v) => update("ignition_energy_j", v)}
          unit="J"
        />
      ) : (
        <p className="muted small">
          Hot-spot temperature is capped at a plausible hot-source value; the
          ignition region radius slider below sets the spot size.
        </p>
      )}

      <Slider
        label="Inlet velocity (Saffire)"
        value={config.inlet_velocity_ms}
        min={0}
        max={2}
        step={0.05}
        onChange={(v) => update("inlet_velocity_ms", v)}
        unit="m/s"
      />

      <div className="btn-row">
        <button className="action-btn primary" onClick={onRun} disabled={busy}>
          {busy ? "Running…" : "Run simulation"}
        </button>
        <button className="action-btn" onClick={onSweep} disabled={busy}>
          O₂ sweep (6 pts)
        </button>
      </div>

      <details
        className="advanced"
        open={advancedOpen}
        onToggle={(e) => setAdvancedOpen(e.currentTarget.open)}
      >
        <summary>Advanced numerical settings</summary>
        <Slider
          label="Grid nx"
          value={config.nx}
          min={16}
          max={512}
          step={16}
          onChange={(v) => update("nx", v)}
          unit="cells"
        />
        <Slider
          label="Grid ny"
          value={config.ny}
          min={16}
          max={512}
          step={16}
          onChange={(v) => update("ny", v)}
          unit="cells"
        />
        <Slider
          label="Δt"
          value={config.dt_s}
          min={0.0001}
          max={0.01}
          step={0.0001}
          onChange={(v) => update("dt_s", v)}
          unit="s"
        />
        <Slider
          label="End time"
          value={config.end_time_s}
          min={0.1}
          max={20}
          step={0.1}
          onChange={(v) => update("end_time_s", v)}
          unit="s"
        />

        <label className="field">
          <span>Wall thermal condition</span>
          <select
            value={config.wall_thermal_mode}
            onChange={(e) => update("wall_thermal_mode", e.target.value)}
          >
            <option value="adiabatic">Adiabatic</option>
            <option value="isothermal">Isothermal wall</option>
          </select>
        </label>
        {config.wall_thermal_mode === "isothermal" && (
          <Slider
            label="Wall temperature"
            value={config.wall_temperature_k}
            min={200}
            max={2500}
            step={10}
            onChange={(v) => update("wall_temperature_k", v)}
            unit="K"
          />
        )}

        <p className="muted small">
          Arrhenius overrides (A, Ea) are exposed in the backend config schema;
          the UI keeps the species-database presets as the source of truth.
        </p>
      </details>
    </div>
  );
}

function Slider({ label, value, min, max, step, onChange, unit }) {
  return (
    <label className="field slider">
      <span>
        {label}
        <b>
          {value} {unit}
        </b>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
      />
    </label>
  );
}