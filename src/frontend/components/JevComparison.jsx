import React from "react";

/**
 * Jev experiment comparison with match percentages: the tier-1 verdict
 * expressed as per-field agreement % against the nearest NASA PSI ground
 * truth (shipped with the triage reply) plus the verdict's own scores.
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
      label: "Peak temperature",
      value: pct(sim.peak_temp_k, gt.peak_temp_k, 2500),
      detail: `${Math.round(sim.peak_temp_k ?? 0)} K vs ${Math.round(gt.peak_temp_k ?? 0)} K`,
    });
    rows.push({
      label: "Flame radius",
      value: pct(sim.max_radius_mm, gt.max_radius_mm, 40),
      detail: `${(sim.max_radius_mm ?? 0).toFixed(1)} mm vs ${(gt.max_radius_mm ?? 0).toFixed(1)} mm`,
    });
    rows.push({
      label: "Oxygen %",
      value: pct(sim.oxygen_pct, gt.oxygen_pct, 40),
      detail: `${(sim.oxygen_pct ?? 0).toFixed(1)} % vs ${(gt.oxygen_pct ?? 0).toFixed(1)} %`,
    });
    rows.push({
      label: "Pressure",
      value: pct(sim.ambient_pressure_bar, gt.ambient_pressure_bar, 3),
      detail: `${(sim.ambient_pressure_bar ?? 0).toFixed(2)} vs ${(gt.ambient_pressure_bar ?? 0).toFixed(2)} bar`,
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
        {v?.buoyancy_driven_convection != null && (
          <span className="chip">
            buoyant: {String(v.buoyancy_driven_convection)}
          </span>
        )}
      </div>

      {!v && (
        <p className="muted small">
          Run a simulation, then run the tier-1 verdict to compare it against
          the nearest NASA PSI ground-truth run.
        </p>
      )}

      {rows.length > 0 && (
        <div className="pct-rows">
          {rows.map((r) =>
            r.value == null ? null : (
              <div className="pct-row" key={r.label}>
                <span className="pct-label">{r.label}</span>
                <span className="pct-bar">
                  <i style={{ width: `${Math.min(r.value, 100)}%` }} />
                </span>
                <span className="pct-val">{r.value.toFixed(0)}%</span>
                <span className="muted small pct-detail">{r.detail}</span>
              </div>
            )
          )}
        </div>
      )}

      {v && (
        <table className="verdict-table">
          <tbody>
            {verdictRows.map(([k, val]) => (
              <tr key={k}>
                <th scope="row">{k}</th>
                <td>{val}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {v?.notes && <p className="muted small jev-notes">{v.notes}</p>}

      <button
        className="action-btn"
        onClick={onTriage}
        disabled={!connected || busy || !onTriage}
        style={{ marginTop: 10 }}
      >
        {v ? "Re-run Jev triage" : "Run Jev triage"}
      </button>
    </div>
  );
}
