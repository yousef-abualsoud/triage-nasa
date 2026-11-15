import React from "react";

/**
 * Cursor-following value box shared by the D3 charts. `hover` is either null
 * or { left, top, flip, title, rows: [{ label, value, color }] }.
 */
export default function ChartTooltip({ hover }) {
  if (!hover) return null;
  return (
    <div
      className={`chart-tooltip ${hover.flip ? "flip" : ""}`}
      style={{ left: hover.left, top: hover.top }}
      role="status"
      aria-live="polite"
    >
      <div className="chart-tooltip-title">{hover.title}</div>
      {hover.rows.map((row, index) => (
        <div className="chart-tooltip-row" key={`${row.label}-${index}`}>
          {row.color ? (
            <i className="sw" style={{ background: row.color }} />
          ) : null}
          <span>{row.label}</span>
          <b>{row.value}</b>
        </div>
      ))}
    </div>
  );
}
