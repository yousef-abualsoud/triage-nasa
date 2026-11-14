import React, { useEffect, useMemo, useRef } from "react";
import * as d3 from "d3";

/**
 * 2D spatial temperature heatmap with a frame scrubber.
 * Renders the [ny][nx] Kelvin field from the solver via canvas + d3 scales.
 * Zero-G: spherical diffusion flame. 1G: buoyant teardrop. Saffire: tilted.
 */
export default function FlameField2D({
  frame,
  time,
  frameIndex,
  frameCount,
  onScrub,
  gravityMode,
  finalData,
}) {
  const canvasRef = useRef(null);
  const [dims, setDims] = React.useState({ w: 480, h: 480 });

  const colorScale = useMemo(
    () =>
      d3
        .scaleSequential()
        .domain([300, 2500])
        .interpolator(d3.interpolateRgbBasis(["#02020f", "#1a237e", "#b71c1c", "#ff9800", "#ffe082", "#ffffff"])),
    []
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !frame) return;
    const ctx = canvas.getContext("2d");
    const ny = frame.length;
    const nx = frame[0].length;
    const img = ctx.createImageData(nx, ny);
    let max = 300;
    for (let j = 0; j < ny; j++) {
      for (let i = 0; i < nx; i++) {
        if (frame[j][i] > max) max = frame[j][i];
      }
    }
    // Normalize color domain to this run's dynamic range for contrast.
    const scale = d3
      .scaleSequential()
      .domain([300, Math.min(max, 3000)])
      .interpolator(d3.interpolateRgbBasis(["#02020f", "#1a237e", "#b71c1c", "#ff9800", "#ffe082", "#4dd0e1"]));
    for (let j = 0; j < ny; j++) {
      for (let i = 0; i < nx; i++) {
        const rgb = d3.color(scale(frame[j][i]));
        const o = (j * nx + i) * 4;
        img.data[o] = rgb.r;
        img.data[o + 1] = rgb.g;
        img.data[o + 2] = rgb.b;
        img.data[o + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
  }, [frame]);

  const info = finalData ?? {};
  const modeLabel = {
    zero_g: "Zero-G — diffusion sphere",
    iss_micro_g: "ISS Micro-G — jitter",
    earth_1g: "Earth 1G — buoyant teardrop",
    mars_g: "Mars 0.38G — partial gravity",
    moon_g: "Moon 0.165G — partial gravity",
  }[gravityMode] ?? gravityMode;

  return (
    <div className="panel flame-panel">
      <div className="panel-head">
        <h2>Flame Field (2D)</h2>
        <span className="chip">{modeLabel}</span>
        {time != null && <span className="chip">t = {time.toFixed ? time.toFixed(3) : time} s</span>}
      </div>
      <div className="flame-canvas-wrap">
        <canvas
          ref={canvasRef}
          width={frame?.[0]?.length ?? 128}
          height={frame?.length ?? 128}
          style={{
            width: "100%",
            height: "auto",
            imageRendering: "pixelated",
            borderRadius: 8,
          }}
        />
        {!frame && (
          <div className="flame-placeholder">Waiting for solver frames…</div>
        )}
      </div>
      <div className="scrubber-row">
        <input
          type="range"
          min={0}
          max={Math.max(frameCount - 1, 0)}
          value={Math.min(frameIndex, Math.max(frameCount - 1, 0))}
          onChange={(e) => onScrub(parseInt(e.target.value, 10))}
          aria-label="Time scrubber"
        />
        <span className="muted small">
          frame {frameIndex + 1}/{frameCount}
        </span>
      </div>
      {info && (
        <div className="final-stats">
          <Stat label="Peak T" value={`${Math.round(info.peak_temp_k ?? 0)} K`} />
          <Stat
            label="Max radius"
            value={`${((info.max_flame_radius_m ?? 0) * 1000).toFixed(1)} mm`}
          />
          <Stat
            label="Quenched"
            value={info.quenched ? "yes" : "no"}
            warn={info.quenched}
          />
          <Stat
            label="Stability"
            value={`${(info.stability ?? 0).toFixed(0)}/100`}
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