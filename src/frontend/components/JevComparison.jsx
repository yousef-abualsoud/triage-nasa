import React from "react";

/**
 * Compact Jev experiment comparison for the Tab-2 left rail: per-field
 * agreement % against the nearest NASA PSI ground truth (shipped with the
 * triage reply), plus the tier-1 verdict as a dense two-column key/value
 * grid so the whole panel fits under the visualizer without scrolling.
 */
export default function JevComparison({ verdictMsg, sim, onTriage, busy, connected }) {
  const v = verdictMsg?.verdict;
  const gt = verdictMsg?.ground_truth;

  const pct = (a, b, scale) => {
    if (a == null || b == null) return null;
    return Math.max(0, 100 - (Math.abs(a - b) / scale) * 100);
  };

  const rows = [];
  if (v && sim && gt) {
    rows.push({
      label: "Peak temp",
      value: pct(sim.peak_temp_k, gt.peak_temp_k, 2500),
      detail: `sim ${Math.round(sim.peak_temp_k ?? 0)} K vs NASA ${Math.round(gt.peak_temp_k ?? 0)} K`,
    });
    rows.push({
      label: "Flame radius",
      value: pct(sim.max_radius_mm, gt.max_radius_mm, 40),
      detail: `sim ${(sim.max_radius_mm ?? 0).toFixed(1)} mm vs NASA ${(gt.max_radius_mm ?? 0).toFixed(1)} mm`,
    });
    rows.push({
      label: "Oxygen",
      value: pct(sim.oxygen_pct, gt.oxygen_pct, 40),
      detail: `sim ${(sim.oxygen_pct ?? 0).toFixed(1)} % vs NASA ${(gt.oxygen_pct ?? 0).toFixed(1)} %`,
    });
    rows.push({
      label: "Pressure",
      value: pct(sim.ambient_pressure_bar, gt.ambient_pressure_bar, 3),
      detail: `sim ${(sim.ambient_pressure_bar ?? 0).toFixed(2)} bar vs NASA ${(gt.ambient_pressure_bar ?? 0).toFixed(2)} bar`,
    });
  }

  const verdictRows = v
    ? [
        ["Morphology", v.flame_morphology],
        ["Profile match", v.nasa_experiment_profile_match],
        ["Buoyant convection", String(v.buoyancy_driven_convection)],
        ["Radiant loss critical", String(v.radiant_heat_loss_critical)],
        ["Soot score", `${Number(v.soot_volume_fraction_score).toFixed(1)}/100`],
        ["Stability", `${Number(v.stability_score).toFixed(1)}/100`],
        ["Delta", `${Number(v.delta_score).toFixed(1)}/100`],
        ["Confidence", Number(v.confidence_score).toFixed(2)],
      ]
    : [];

  return (
    <div className="panel jev-panel">
      <div className="panel-head">
        <h2>Jev Experiment Comparison</h2>
        <button
          type="button"
          className="action-btn mini-btn"
          onClick={onTriage}
          disabled={!connected || busy || !onTriage}
        >
          {v ? "Re-run triage" : "Run triage"}
        </button>
      </div>

      {!v && (
        <p className="muted small jev-empty">
          Run the tier-1 verdict to compare this run against the nearest NASA
          PSI ground truth.
        </p>
      )}

      {rows.length > 0 && (
        <div className="pct-rows">
          {rows.map((r) =>
            r.value == null ? null : (
              <div className="pct-row" key={r.label} title={r.detail}>
                <span className="pct-label">{r.label}</span>
                <span className="pct-bar">
                  <i style={{ width: `${Math.min(r.value, 100)}%` }} />
                </span>
                <span className="pct-val">{r.value.toFixed(0)}%</span>
              </div>
            )
          )}
        </div>
      )}

      {v && (
        <div className="kv-grid">
          {verdictRows.map(([k, val]) => (
            <div className="kv" key={k}>
              <span>{k}</span>
              <b>{val}</b>
            </div>
          ))}
        </div>
      )}

      {v?.notes && (
        <p className="muted small jev-notes" title={v.notes}>
          {v.notes}
        </p>
      )}
    </div>
  );
}
