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
  const match = verdictMsg?.match;

  const pct = (a, b, scale) => {
    if (a == null || b == null) return null;
    return Math.max(0, 100 - (Math.abs(a - b) / scale) * 100);
  };
  const num = (x, digits = 2) => (x == null ? "—" : Number(x).toFixed(digits));

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
    if (sim.burn_duration_s != null && gt.burn_duration_s != null) {
      rows.push({
        label: "Burn duration",
        value: pct(sim.burn_duration_s, gt.burn_duration_s, 30),
        detail: `sim ${Number(sim.burn_duration_s).toFixed(1)} s vs NASA ${Number(gt.burn_duration_s).toFixed(1)} s`,
      });
    }
  }

  const gtIdentity = gt?.test_point
    ? `${gt.investigation || gt.accession || "PSI"} · ${gt.test_point}`
    : gt?.investigation ||
      (gt?.source === "synthetic"
        ? `Offline surrogate${gt.experiment_id ? ` · ${gt.experiment_id}` : ""}`
        : null);

  const runnerUp = match?.runner_up;
  const runnerId = runnerUp
    ? runnerUp.test_point ||
      runnerUp.experiment_id ||
      runnerUp.accession ||
      "surrogate"
    : null;
  const matchTitle = match?.matched
    ? [
        match.pool === "real"
          ? match.synthetic_candidates > 0
            ? `real PSI flight data preferred over ${match.synthetic_candidates} surrogate candidate(s)`
            : "nearest real PSI flight data"
          : "no real PSI run in this fuel/gravity class; surrogate used",
        `normalized match distance ${num(match.distance, 3)}`,
        `ΔO2 ${num(match.deltas?.oxygen_pct, 2)} %, ΔP ${num(match.deltas?.pressure_bar, 3)} bar, Δu ${num(match.deltas?.velocity_ms, 3)} m/s`,
        `components O2 ${num(match.components?.oxygen, 4)} + P ${num(match.components?.pressure, 4)} + u ${num(match.components?.velocity, 4)} + penalty ${num(match.components?.extinction_penalty, 4)}`,
        ...(match.extinction_mismatch ? ["outcome mismatch penalty +0.15"] : []),
        ...(runnerUp
          ? [`runner-up ${runnerId} at ${num(runnerUp.distance, 3)}`]
          : []),
      ].join(" · ")
    : match?.reason || "";

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
        <div className="jev-title">
          <h2>Jev Experiment Comparison</h2>
          {v && (
            <span
              className={`chip ${v.engine === "local" ? "chip-warn" : ""}`}
              title={
                v.engine === "local"
                  ? "Deterministic local heuristic — no NanoGPT/Jev call"
                  : "Verdict produced by typesafe/jev-latest on NanoGPT"
              }
            >
              {v.engine === "local" ? "local" : "Jev"}
            </span>
          )}
        </div>
        <button
          type="button"
          className="action-btn mini-btn"
          onClick={onTriage}
          disabled={!connected || busy || !onTriage}
        >
          {v ? "Re-run" : "Run triage"}
        </button>
      </div>

      {gtIdentity && (
        <p
          className="muted small jev-exp"
          title={[gt.fuel_blend, gt.atmosphere, gt.facility].filter(Boolean).join(" · ")}
        >
          {gt.source === "synthetic" ? "⚠ " : ""}
          {gtIdentity}
          {gt.fuel_blend ? ` · ${gt.fuel_blend}` : ""}
        </p>
      )}

      {gt?.burn_duration_s != null && (
        <p className="muted small jev-exp">
          NASA: {Number(gt.burn_duration_s).toFixed(1)} s burn ·{" "}
          {gt.extinction ? "extinguished" : "stable"} · P{" "}
          {Number(gt.ambient_pressure_bar).toFixed(2)} bar
          {gt.peak_pmt_ua != null ? ` · PMT ${Number(gt.peak_pmt_ua).toFixed(2)} µA` : ""}
        </p>
      )}

      {match?.matched && (
        <>
          <p className="muted small jev-why" title={matchTitle}>
            Why:{" "}
            <span className={match.pool === "synthetic" ? "jev-warn" : ""}>
              {match.pool === "synthetic" ? "⚠ surrogate" : "real PSI"}
            </span>
            {" · "}ΔO₂ {num(match.deltas?.oxygen_pct, 1)}% · ΔP{" "}
            {num(match.deltas?.pressure_bar, 2)} bar
            {match.deltas?.velocity_ms > 0
              ? ` · Δu ${num(match.deltas.velocity_ms, 2)} m/s`
              : ""}
            {match.extinction_mismatch ? " · outcome +0.15" : ""}
            {" → d "}
            {num(match.distance, 3)}
          </p>
          <p className="muted small jev-why jev-why-sub" title={matchTitle}>
            {runnerUp
              ? `next ${runnerUp.source === "psi" ? "real" : "surrogate"} ${runnerId} ${num(runnerUp.distance, 3)} · `
              : "no runner-up · "}
            {match.real_candidates} real / {match.synthetic_candidates} surrogate
            {match.pool === "real" && match.synthetic_candidates > 0
              ? " · real preferred"
              : ""}
          </p>
        </>
      )}
      {match && !match.matched && (
        <p className="small jev-why jev-nomatch" title={match.reason}>
          No PSI match — {match.reason}. Comparison withheld.
        </p>
      )}

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
