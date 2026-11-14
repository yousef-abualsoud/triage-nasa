import React, { useState } from "react";

/**
 * Digital-twin controls: primary physical parameters, custom fuel presets
 * (persisted server-side via fuel_list/fuel_save/fuel_delete), custom
 * gravity, iteration-count-driven run length, and a "New fuel" dialog that
 * edits the preset's database variables.
 */
export default function ControlPanel({
  config,
  update,
  fuelInfo,
  onSaveFuel,
  onDeleteFuel,
  onRun,
  busy,
}) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [fuelModal, setFuelModal] = useState(null); // null | {key, data}

  const fuels = fuelInfo?.fuels ?? {}; // key -> {name, formula, custom}
  const fields = fuelInfo?.fields ?? {}; // field -> {min, max}

  const openNewFuel = () =>
    setFuelModal({
      key: "",
      data: {
        name: "",
        pre_exponential_factor: 1e8,
        activation_energy_j_per_mol: 1.4e5,
        lower_heating_value_j_per_kg: 5e7,
        specific_heat_j_per_kgK: 2200,
        thermal_conductivity_w_per_mK: 0.03,
        species_diffusivity_m2_per_s: 2e-5,
        stoichiometric_fuel_o2_ratio: 0.5,
        adiabatic_flame_temp_k: 2300,
        soot_tendency_index: 0.15,
        max_laminar_flame_speed_m_per_s: 0.45,
        reaction_order_fuel: 0.3,
        reaction_order_oxygen: 1.2,
      },
    });

  const openEditFuel = (key) => {
    if (!fuels[key]) return;
    // Load the full preset from the server via fuel_list (includes chemistry).
    setFuelModal({ key, data: null, loading: true, preset: fuels[key] });
  };

  return (
    <div className="panel control-panel">
      <h2>Digital Twin Controls</h2>

      <label className="field">
        <span>Fuel preset</span>
        <select
          value={config.fuel}
          onChange={(e) => update("fuel", e.target.value)}
        >
          {Object.entries(fuels).map(([k, f]) => (
            <option key={k} value={k}>
              {f.name ?? k}
              {f.custom ? " (custom)" : ""}
            </option>
          ))}
        </select>
      </label>
      <div className="btn-row fuel-actions">
        <button
          type="button"
          className="action-btn"
          onClick={openNewFuel}
          disabled={busy}
        >
          + New fuel
        </button>
        {fuels[config.fuel]?.custom && (
          <>
            <button
              type="button"
              className="action-btn"
              onClick={() => openEditFuel(config.fuel)}
              disabled={busy}
            >
              Edit
            </button>
            <button
              type="button"
              className="action-btn danger-btn"
              onClick={() => onDeleteFuel(config.fuel)}
              disabled={busy}
            >
              Delete
            </button>
          </>
        )}
      </div>

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
          <option value="zero_g">Zero-G (ideal)</option>
          <option value="iss_micro_g">ISS Micro-G (jitter)</option>
          <option value="earth_1g">Earth 1G</option>
          <option value="mars_g">Mars 0.38G</option>
          <option value="moon_g">Moon 0.165G</option>
          <option value="custom">Custom gravity…</option>
        </select>
      </label>
      {config.gravity_mode === "custom" && (
        <>
          <Slider
            label="Custom g magnitude"
            value={config.custom_gravity_m_per_s2}
            min={0}
            max={50}
            step={0.1}
            onChange={(v) => update("custom_gravity_m_per_s2", v)}
            unit="m/s²"
          />
          <Slider
            label="Custom g-jitter"
            value={config.custom_g_jitter_m_per_s2}
            min={0}
            max={1}
            step={0.01}
            onChange={(v) => update("custom_g_jitter_m_per_s2", v)}
            unit="m/s²"
          />
        </>
      )}

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
          Hot-spot ignition prescribes the temperature directly inside the
          ignition region (advanced: region radius).
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
          onChange={(v) => update("nx", Math.round(v))}
          unit="cells"
          digits={0}
        />
        <Slider
          label="Grid ny"
          value={config.ny}
          min={16}
          max={512}
          step={16}
          onChange={(v) => update("ny", Math.round(v))}
          unit="cells"
          digits={0}
        />
        <Slider
          label="Step size Δt"
          value={config.dt_s}
          min={0.001}
          max={1}
          step={0.0001}
          onChange={(v) => update("dt_s", v)}
          unit="s"
        />
        <Slider
          label="Iteration count"
          value={config.iteration_count}
          min={1}
          max={20000}
          step={1}
          onChange={(v) => update("iteration_count", Math.round(v))}
          unit="steps"
          digits={0}
        />
        <Slider
          label="Frame every N steps"
          value={config.output_interval_steps}
          min={1}
          max={64}
          step={1}
          onChange={(v) => update("output_interval_steps", Math.round(v))}
          unit="steps"
          digits={0}
        />
        <Slider
          label="Domain length"
          value={config.domain_length_m}
          min={0.01}
          max={0.5}
          step={0.005}
          onChange={(v) => update("domain_length_m", v)}
          unit="m"
        />
        <Slider
          label="Domain height"
          value={config.domain_height_m}
          min={0.01}
          max={0.5}
          step={0.005}
          onChange={(v) => update("domain_height_m", v)}
          unit="m"
        />
        <Slider
          label="Ignition region radius"
          value={config.ignition_region_m}
          min={0.001}
          max={0.02}
          step={0.0005}
          onChange={(v) => update("ignition_region_m", v)}
          unit="m"
        />
        <p className="muted small">
          Wall thermal condition was removed from the UI per spec: the solver
          runs adiabatic walls and the C++ engine will match this seam.
        </p>
        <p className="muted small">
          Arrhenius overrides (A, Ea) live in the fuel presets — create or
          edit a custom preset to change the database variables.
        </p>
      </details>

      {fuelModal && (
        <FuelModal
          modal={fuelModal}
          fields={fields}
          fuels={fuels}
          onClose={() => setFuelModal(null)}
          onSave={async (key, data) => {
            await onSaveFuel(key, data);
            setFuelModal(null);
          }}
        />
      )}
    </div>
  );
}

/**
 * Slider with inline direct value editing: the numeric readout is a
 * contenteditable-style input — click the value, type, Enter/blur commits.
 * The range slider remains the second way to change the same value.
 */
function Slider({ label, value, min, max, step, onChange, unit, digits }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const d = digits ?? (step < 0.01 ? 4 : step < 1 ? 2 : 0);
  const shown = value != null ? Number(value).toFixed(d) : "";
  const commit = () => {
    setEditing(false);
    const v = parseFloat(draft);
    if (Number.isFinite(v)) {
      onChange(Math.min(max, Math.max(min, v)));
    }
  };
  return (
    <label className="field slider">
      <span>
        {label}
        {editing ? (
          <input
            className="value-edit"
            autoFocus
            type="text"
            inputMode="decimal"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Enter") commit();
              if (e.key === "Escape") setEditing(false);
            }}
            aria-label={`${label} — type a value`}
          />
        ) : (
          <b
            className="value-edit-hit"
            onClick={() => {
              setDraft(shown);
              setEditing(true);
            }}
            title="Click to type a value"
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                setDraft(shown);
                setEditing(true);
              }
            }}
          >
            {shown} {unit}
          </b>
        )}
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

/**
 * Custom fuel preset modal: name + chemistry database variables with the
 * server-provided validation ranges (fuelInfo.fields).
 */
function FuelModal({ modal, fields, fuels, onClose, onSave }) {
  const [key, setKey] = useState(modal.key);
  const [data, setData] = useState(modal.data ?? {});
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const set = (k, v) => setData((d) => ({ ...d, [k]: v }));
  const fieldNames = {
    pre_exponential_factor: ["Arrhenius A", "1/s^n"],
    activation_energy_j_per_mol: ["Activation energy Ea", "J/mol"],
    lower_heating_value_j_per_kg: ["Lower heating value", "J/kg"],
    specific_heat_j_per_kgK: ["Specific heat cp", "J/(kg·K)"],
    thermal_conductivity_w_per_mK: ["Thermal conductivity k", "W/(m·K)"],
    species_diffusivity_m2_per_s: ["Species diffusivity D", "m²/s"],
    stoichiometric_fuel_o2_ratio: ["Stoich fuel:O₂ ratio", "—"],
    adiabatic_flame_temp_k: ["Adiabatic flame temp", "K"],
    soot_tendency_index: ["Soot tendency", "0-1"],
    max_laminar_flame_speed_m_per_s: ["Max laminar flame speed", "m/s"],
    reaction_order_fuel: ["Reaction order (fuel)", "—"],
    reaction_order_oxygen: ["Reaction order (O₂)", "—"],
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="Custom fuel preset">
      <div className="modal fuel-modal">
        <div className="panel-head">
          <h2>{modal.key ? `Edit preset ${modal.key}` : "New custom fuel preset"}</h2>
          <button className="close-btn" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <label className="field">
          <span>Preset key (uppercase)</span>
          <input
            className="text-input"
            value={key}
            onChange={(e) => setKey(e.target.value.toUpperCase())}
            placeholder="e.g. C2H6"
            disabled={!!modal.key}
          />
        </label>
        <label className="field">
          <span>Display name</span>
          <input
            className="text-input"
            value={data.name ?? ""}
            onChange={(e) => set("name", e.target.value)}
            placeholder="e.g. Ethane"
          />
        </label>
        {Object.entries(fieldNames).map(([f, [label, unit]]) => {
          const range = fields[f];
          const v = data[f];
          return (
            <label className="field" key={f}>
              <span>
                {label}
                <b>
                  {v != null ? Number(v).toPrecision(3) : "—"} {unit}
                </b>
              </span>
              <input
                type="range"
                min={range?.min ?? 0}
                max={range?.max ?? 1}
                step={(range?.max - range?.min) / 500 || 0.001}
                value={v ?? (range?.min ?? 0)}
                onChange={(e) => set(f, parseFloat(e.target.value))}
              />
            </label>
          );
        })}
        {error && <p className="error-text">{error}</p>}
        <div className="btn-row">
          <button
            className="action-btn primary"
            disabled={saving || !key.trim()}
            onClick={async () => {
              setSaving(true);
              setError(null);
              try {
                await onSave(key.trim(), data);
              } catch (e) {
                setError(String(e?.message ?? e));
                setSaving(false);
              }
            }}
          >
            {saving ? "Saving…" : modal.key ? "Save changes" : "Create preset"}
          </button>
          <button className="action-btn" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}