/**
 * Rule-based run diagnostics shared by the Tab-3 Suggestions panel and the
 * exported PDF report. Keeping one implementation means the downloaded report
 * cannot drift from what the dashboard shows.
 */
export function buildSuggestions(history, finalData) {
  if (!history?.length) return [];
  const out = [];
  const last = history[history.length - 1];
  const peak = finalData?.peak_temp_k ?? last?.peak_temp_k ?? 0;
  const burned = last?.fuel_burned_fraction ?? 0;
  const stability = finalData?.stability ?? 0;
  const quenched = finalData?.quenched;
  const growth =
    (history[history.length - 1]?.max_flame_radius_m ?? 0) -
    (history[0]?.max_flame_radius_m ?? 0);

  if (quenched) {
    out.push(
      "Flame quenched this run: peak temperature collapsed toward ambient. Raise O₂ % or reduce dilution to sustain combustion."
    );
  }
  if (stability < 40) {
    out.push(
      `Stability ${(stability ?? 0).toFixed(0)}/100 is low — refine near this boundary with a parameter sweep to map the quench limit.`
    );
  }
  if (growth > 0) {
    out.push(
      `Flame radius grew ${Math.round(growth * 1000)} mm over the run: still expanding at t_end. Increase iteration count to capture the full burn-out.`
    );
  } else {
    out.push(
      "Flame radius is static or shrinking: the front has stalled or the fuel is burned out; extend iterations only if burned fraction is still rising."
    );
  }
  if (burned > 0.8) {
    out.push(
      `${(burned * 100).toFixed(0)}% of fuel burned: near-complete consumption. For habitat safety margins, evaluate quench boundary with lower O₂ sweeps.`
    );
  }
  if (peak > 1800) {
    out.push(
      `Peak ${Math.round(peak)} K exceeds typical radiant-loss thresholds — radiant heat loss is critical for cabin materials (Jev flag set accordingly).`
    );
  }
  const diag = finalData?.diagnostics;
  if (diag && Math.abs(Number(diag.mass_relative_error ?? 0)) > 0.05) {
    out.push(
      `Solver diagnostic: mass budget drift ${(Number(diag.mass_relative_error) * 100).toFixed(1)}% — this follows the document's continuity/density formulation and is tracked for revision (R1/R14).`
    );
  }
  if (diag?.substeps_capped) {
    out.push(
      "Adaptive substepping hit its per-step cap: reduce Δt or Nᵣ below the reported limit for a resolved run."
    );
  }
  return out;
}
