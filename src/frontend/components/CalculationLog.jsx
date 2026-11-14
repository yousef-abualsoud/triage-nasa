import React, { useEffect, useRef } from "react";

/**
 * Live calculation log: renders the current solver scalars and a streaming
 * console-style trace as the run progresses. The mock solver computes one
 * message per completion (history-driven); the C++ solver will stream
 * per-iteration rows through the same props.
 */
export default function CalculationLog({ history, times, busy, finalData }) {
  const traceRef = useRef(null);
  const lines = history ?? [];

  // Keep the newest line in view as rows stream in.
  useEffect(() => {
    const el = traceRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  const last = lines[lines.length - 1];
  const fmt = (v, d = 3) => (v == null ? "—" : Number(v).toFixed(d));

  return (
    <div className="panel calc-panel">
      <div className="panel-head">
        <h2>Active Calculations</h2>
        <span className={`chip ${busy ? "pulse" : ""}`}>
          {busy ? "computing…" : "idle"}
        </span>
      </div>
      <div className="calc-current">
        <div className="stat">
          <span className="stat-label">t</span>
          <span className="stat-value">{fmt(last?.t_s ?? 0)} s</span>
        </div>
        <div className="stat">
          <span className="stat-label">peak T</span>
          <span className="stat-value">{fmt(last?.peak_temp_k ?? 0, 0)} K</span>
        </div>
        <div className="stat">
          <span className="stat-label">mean T</span>
          <span className="stat-value">{fmt(last?.mean_temp_k ?? 0, 0)} K</span>
        </div>
        <div className="stat">
          <span className="stat-label">flame R</span>
          <span className="stat-value">
            {fmt((last?.max_flame_radius_m ?? 0) * 1000, 2)} mm
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">burned</span>
          <span className="stat-value">
            {fmt((last?.fuel_burned_fraction ?? 0) * 100, 1)} %
          </span>
        </div>
      </div>
      <div className="calc-trace" ref={traceRef} aria-live="polite">
        {lines.length === 0 && (
          <div className="muted small">No solver output yet — run a simulation.</div>
        )}
        {lines.map((h, i) => (
          <div className="trace-line" key={i}>
            <span className="trace-t">
              [{h.iteration ?? i}] t={fmt(h.t_s)}s
            </span>
            <span>
              peak={fmt(h.peak_temp_k, 0)}K mean={fmt(h.mean_temp_k, 0)}K{" "}
              R={fmt((h.max_flame_radius_m ?? 0) * 1000, 2)}mm{" "}
              burned={fmt((h.fuel_burned_fraction ?? 0) * 100, 1)}%{" "}
              soot={fmt(h.soot_index, 2)}
            </span>
          </div>
        ))}
        {busy && (
          <div className="trace-line pulse">
            <span className="trace-t">…</span>
            <span>computing next iteration</span>
          </div>
        )}
      </div>
      {finalData && (
        <div className="final-stats">
          <Stat label="Peak T" value={`${Math.round(finalData.peak_temp_k ?? 0)} K`} />
          <Stat
            label="Max radius"
            value={`${((finalData.max_flame_radius_m ?? 0) * 1000).toFixed(1)} mm`}
          />
          <Stat
            label="Quenched"
            value={finalData.quenched ? "yes" : "no"}
            warn={finalData.quenched}
          />
          <Stat
            label="Stability"
            value={`${(finalData.stability ?? 0).toFixed(0)}/100`}
          />
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, warn }) {
  return (
    <div className={`stat ${warn ? "warn" : ""}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
    </div>
  );
}