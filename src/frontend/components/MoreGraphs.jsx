import React, { useEffect, useRef } from "react";
import * as d3 from "d3";
import BurnCurveOverlay from "./BurnCurveOverlay.jsx";

/**
 * Tab 3: additional graphs — burn curves vs NASA PSI telemetry, soot index &
 * mean temperature history, fuel burned fraction, buoyancy kinetic energy,
 * and the radial temperature profile of the current frame — plus heuristic
 * suggestions read off the run's own numbers (grounded, no external calls).
 */
export default function MoreGraphs({
  history,
  frame,
  frameIndex,
  ambientK,
  finalData,
  groundTruth,
  radialFrames = [],
  finalRadial = null,
}) {
  return (
    <div className="graphs-grid">
      <div className="graphs-wide">
        <BurnCurveOverlay simHistory={history} groundTruth={groundTruth} />
      </div>
      <SolverRadialFields finalRadial={finalRadial} />
      <SpeciesProfile finalRadial={finalRadial} />
      <div className="graphs-wide">
        <RadialTimeHeatmap radialFrames={radialFrames} />
      </div>
      <HistoryGraph
        history={history}
        series={[
          { key: "soot_index", label: "soot index", color: "#b0a8ff", scale: "auto" },
          { key: "mean_temp_k", label: "mean T (K)", color: "#ff9e40", scale: "auto" },
        ]}
        title="Soot & Mean Temperature"
        aria="Soot index and mean temperature history"
      />
      <HistoryGraph
        history={history}
        series={[{ key: "fuel_burned_fraction", label: "burned fuel", color: "#66bb6a", scale: [0, 1] }]}
        title="Fuel Burned Fraction"
        aria="Fuel burned fraction over iterations"
      />
      <HistoryGraph
        history={history}
        series={[{ key: "buoyancy_ke", label: "buoyancy KE", color: "#4dd0e1", scale: "auto" }]}
        title="Buoyancy Kinetic Energy"
        aria="Buoyancy kinetic energy over iterations"
      />
      <RadialProfile frame={frame} frameIndex={frameIndex} ambientK={ambientK} />
      <Suggestions history={history} finalData={finalData} />
    </div>
  );
}

function HistoryGraph({ history, series, title, aria }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!history?.length) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = 430;
    const H = 200;
    const M = { top: 20, right: 16, bottom: 32, left: 46 };

    const x = d3
      .scaleLinear()
      .domain(d3.extent(history, (h) => h.iteration ?? 0) ?? [0, 1])
      .nice()
      .range([M.left, W - M.right]);

    svg.attr("viewBox", `0 0 ${W} ${H}`);
    svg
      .append("g")
      .attr("transform", `translate(0,${H - M.bottom})`)
      .call(d3.axisBottom(x).ticks(5));

    series.forEach((s, si) => {
      const vals = history.map((h) => h[s.key]).filter((v) => v != null);
      if (!vals.length) return;
      let domain;
      if (Array.isArray(s.scale)) {
        domain = s.scale;
      } else {
        const ext = d3.extent(vals);
        domain = [Math.min(ext[0], 0), ext[1] * 1.08 || 1];
      }
      const y = d3
        .scaleLinear()
        .domain(domain)
        .nice()
        .range([H - M.bottom, M.top]);
      if (si === 0) {
        svg
          .append("g")
          .attr("transform", `translate(${M.left},0)`)
          .call(d3.axisLeft(y).ticks(4));
      }
      const line = d3
        .line()
        .x((h) => x(h.iteration ?? 0))
        .y((h) => y(h[s.key]))
        .curve(d3.curveMonotoneX)
        .defined((h) => h[s.key] != null);
      svg
        .append("path")
        .datum(history)
        .attr("fill", "none")
        .attr("stroke", s.color)
        .attr("stroke-width", 2)
        .attr("d", line);
    });

    svg
      .append("text")
      .attr("x", W / 2)
      .attr("y", H - 4)
      .attr("class", "axis-label")
      .attr("text-anchor", "middle")
      .text("iteration");
  }, [history, series]);

  return (
    <div className="panel mini-graph-panel">
      <div className="panel-head">
        <h2>{title}</h2>
        <span className="legend">
          {series.map((s) => (
            <React.Fragment key={s.key}>
              <i className="sw" style={{ background: s.color }} /> {s.label}
            </React.Fragment>
          ))}
        </span>
      </div>
      <svg ref={svgRef} className="burn-svg" role="img" aria-label={aria} />
      {!history?.length && (
        <p className="muted small">Run a simulation to populate this graph.</p>
      )}
    </div>
  );
}

function RadialProfile({ frame, frameIndex, ambientK }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!frame?.length) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const ny = frame.length;
    const nx = frame[0].length;
    // Radial profile from the domain center: T(r) averaged over the angle.
    const cx = (nx - 1) / 2;
    const cy = (ny - 1) / 2;
    const maxR = Math.min(cx, cy);
    const bins = 48;
    const sums = new Float64Array(bins);
    const counts = new Float64Array(bins);
    for (let j = 0; j < ny; j++) {
      for (let i = 0; i < nx; i++) {
        const r = Math.hypot(i - cx, j - cy) / maxR; // 0..1
        const b = Math.min(Math.floor(r * bins), bins - 1);
        sums[b] += frame[j][i];
        counts[b] += 1;
      }
    }
    const data = [];
    for (let b = 0; b < bins; b++) {
      if (counts[b] > 0) {
        data.push({
          r: (b + 0.5) / bins,
          temp: sums[b] / counts[b],
        });
      }
    }

    const W = 430;
    const H = 200;
    const M = { top: 20, right: 16, bottom: 34, left: 46 };
    const x = d3.scaleLinear().domain([0, 1]).range([M.left, W - M.right]);
    const temps = data.map((d) => d.temp);
    const y = d3
      .scaleLinear()
      .domain([Math.min(ambientK ?? 300, d3.min(temps) ?? 300), (d3.max(temps) ?? 2500) * 1.05])
      .nice()
      .range([H - M.bottom, M.top]);

    svg.attr("viewBox", `0 0 ${W} ${H}`);
    svg
      .append("g")
      .attr("transform", `translate(0,${H - M.bottom})`)
      .call(
        d3
          .axisBottom(x)
          .ticks(5)
          .tickFormat((d) => `${(d * 100).toFixed(0)}%`)
      );
    svg
      .append("g")
      .attr("transform", `translate(${M.left},0)`)
      .call(d3.axisLeft(y).ticks(5));
    svg
      .append("text")
      .attr("x", W / 2)
      .attr("y", H - 4)
      .attr("class", "axis-label")
      .attr("text-anchor", "middle")
      .text("radius (fraction of domain)");
    svg
      .append("text")
      .attr("x", 12)
      .attr("y", M.top - 8)
      .attr("class", "axis-label")
      .text("T (K)");

    const line = d3
      .line()
      .x((d) => x(d.r))
      .y((d) => y(d.temp))
      .curve(d3.curveMonotoneX);
    svg
      .append("path")
      .datum(data)
      .attr("fill", "none")
      .attr("stroke", "#ff7043")
      .attr("stroke-width", 2)
      .attr("d", line);
  }, [frame, frameIndex, ambientK]);

  return (
    <div className="panel mini-graph-panel">
      <div className="panel-head">
        <h2>Radial Temperature Profile</h2>
        <span className="muted small">current frame, angle-averaged</span>
      </div>
      <svg ref={svgRef} className="burn-svg" role="img" aria-label="Radial temperature profile" />
      {!frame?.length && (
        <p className="muted small">Run a simulation to see the radial profile.</p>
      )}
    </div>
  );
}

function SolverRadialFields({ finalRadial }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!finalRadial?.r_m?.length) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = 430;
    const H = 200;
    const M = { top: 20, right: 62, bottom: 34, left: 48 };
    const r = finalRadial.r_m.map((v) => v * 1000);
    const T = finalRadial.temperature_k;
    const q = finalRadial.heat_release_w_m3;
    const x = d3.scaleLinear().domain(d3.extent(r)).range([M.left, W - M.right]);
    const y = d3
      .scaleLinear()
      .domain([Math.min(d3.min(T), 250) * 0.95, d3.max(T) * 1.05])
      .nice()
      .range([H - M.bottom, M.top]);
    const yq = d3
      .scaleSymlog()
      .domain([0, Math.max(d3.max(q) || 1, 1)])
      .range([H - M.bottom, M.top]);

    svg.attr("viewBox", `0 0 ${W} ${H}`);
    svg
      .append("g")
      .attr("transform", `translate(0,${H - M.bottom})`)
      .call(d3.axisBottom(x).ticks(5));
    svg
      .append("g")
      .attr("transform", `translate(${M.left},0)`)
      .call(d3.axisLeft(y).ticks(5));
    svg
      .append("g")
      .attr("transform", `translate(${W - M.right},0)`)
      .call(d3.axisRight(yq).ticks(3, ".1s"));

    const lineT = d3
      .line()
      .x((_, i) => x(r[i]))
      .y((v) => y(v))
      .curve(d3.curveMonotoneX);
    svg
      .append("path")
      .datum(T)
      .attr("fill", "none")
      .attr("stroke", "#ff7043")
      .attr("stroke-width", 2)
      .attr("d", lineT);

    const lineQ = d3
      .line()
      .x((_, i) => x(r[i]))
      .y((v) => yq(v))
      .curve(d3.curveMonotoneX);
    svg
      .append("path")
      .datum(q)
      .attr("fill", "none")
      .attr("stroke", "#66bb6a")
      .attr("stroke-width", 1.5)
      .attr("stroke-dasharray", "4 3")
      .attr("d", lineQ);

    svg
      .append("text")
      .attr("x", W / 2)
      .attr("y", H - 4)
      .attr("class", "axis-label")
      .attr("text-anchor", "middle")
      .text("radius (mm)");
    svg
      .append("text")
      .attr("x", 12)
      .attr("y", M.top - 8)
      .attr("class", "axis-label")
      .text("T (K)");
  }, [finalRadial]);

  return (
    <div className="panel mini-graph-panel">
      <div className="panel-head">
        <h2>Solver Radial Fields</h2>
        <span className="legend">
          <i className="sw" style={{ background: "#ff7043" }} /> T (left)
          <i className="sw" style={{ background: "#66bb6a" }} /> q̇ (right)
        </span>
      </div>
      <svg
        ref={svgRef}
        className="burn-svg"
        role="img"
        aria-label="Radial temperature and heat-release profiles"
      />
      {!finalRadial?.r_m?.length && (
        <p className="muted small">Run a simulation to see the solver radial fields.</p>
      )}
    </div>
  );
}

function SpeciesProfile({ finalRadial }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!finalRadial?.mass_fractions) return;
    const keys = Object.keys(finalRadial.mass_fractions);
    if (!keys.length) return;
    const fuelKey = keys[0];
    const o2Key = keys.find((k) => k === "O2");
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = 430;
    const H = 200;
    const M = { top: 20, right: 16, bottom: 34, left: 52 };
    const r = finalRadial.r_m.map((v) => v * 1000);
    const series = [
      { key: fuelKey, label: fuelKey, color: "#ffb74d", values: finalRadial.mass_fractions[fuelKey] },
      ...(o2Key
        ? [{ key: o2Key, label: o2Key, color: "#4dd0e1", values: finalRadial.mass_fractions[o2Key] }]
        : []),
    ];
    const x = d3.scaleLinear().domain(d3.extent(r)).range([M.left, W - M.right]);
    const ymax = Math.max(0.05, d3.max(series, (s) => d3.max(s.values)) * 1.1);
    const y = d3.scaleLinear().domain([0, ymax]).range([H - M.bottom, M.top]);

    svg.attr("viewBox", `0 0 ${W} ${H}`);
    svg
      .append("g")
      .attr("transform", `translate(0,${H - M.bottom})`)
      .call(d3.axisBottom(x).ticks(5));
    svg
      .append("g")
      .attr("transform", `translate(${M.left},0)`)
      .call(d3.axisLeft(y).ticks(5));

    series.forEach((s) => {
      const line = d3
        .line()
        .x((_, i) => x(r[i]))
        .y((v) => y(v))
        .curve(d3.curveMonotoneX);
      svg
        .append("path")
        .datum(s.values)
        .attr("fill", "none")
        .attr("stroke", s.color)
        .attr("stroke-width", 2)
        .attr("d", line);
    });

    svg
      .append("text")
      .attr("x", W / 2)
      .attr("y", H - 4)
      .attr("class", "axis-label")
      .attr("text-anchor", "middle")
      .text("radius (mm)");
    svg
      .append("text")
      .attr("x", 12)
      .attr("y", M.top - 8)
      .attr("class", "axis-label")
      .text("mass fraction");
  }, [finalRadial]);

  const keys = finalRadial?.mass_fractions ? Object.keys(finalRadial.mass_fractions) : [];
  const o2Key = keys.find((k) => k === "O2");
  return (
    <div className="panel mini-graph-panel">
      <div className="panel-head">
        <h2>Species Profiles</h2>
        <span className="legend">
          {keys.length > 0 && (
            <>
              <i className="sw" style={{ background: "#ffb74d" }} /> {keys[0]}
            </>
          )}
          {o2Key && (
            <>
              <i className="sw" style={{ background: "#4dd0e1" }} /> {o2Key}
            </>
          )}
        </span>
      </div>
      <svg
        ref={svgRef}
        className="burn-svg"
        role="img"
        aria-label="Fuel and oxygen mass-fraction profiles"
      />
      {!keys.length && (
        <p className="muted small">Run a simulation to see species profiles.</p>
      )}
    </div>
  );
}

function RadialTimeHeatmap({ radialFrames }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!radialFrames?.length) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = 880;
    const H = 220;
    const M = { top: 18, right: 82, bottom: 36, left: 52 };
    const r = radialFrames[0].r_m.map((v) => v * 1000);
    const times = radialFrames.map((f) => f.t_s);
    const allT = radialFrames.flatMap((f) => f.temperature_k);
    const x = d3.scaleLinear().domain([r[0], r[r.length - 1]]).range([M.left, W - M.right]);
    const y = d3.scaleLinear().domain([0, d3.max(times) || 1]).range([H - M.bottom, M.top]);
    const color = d3
      .scaleSequential(d3.interpolateInferno)
      .domain([d3.min(allT) ?? 300, d3.max(allT) ?? 3000]);
    const cw = (W - M.left - M.right) / r.length;
    const ch = (H - M.top - M.bottom) / radialFrames.length;

    svg.attr("viewBox", `0 0 ${W} ${H}`);
    radialFrames.forEach((f, ti) => {
      f.temperature_k.forEach((temp, ri) => {
        svg
          .append("rect")
          .attr("x", x(r[ri]) - cw / 2)
          .attr("y", y(f.t_s) - ch / 2)
          .attr("width", cw + 0.4)
          .attr("height", ch + 0.4)
          .attr("fill", color(temp));
      });
    });

    svg
      .append("g")
      .attr("transform", `translate(0,${H - M.bottom})`)
      .call(d3.axisBottom(x).ticks(6));
    svg
      .append("g")
      .attr("transform", `translate(${M.left},0)`)
      .call(d3.axisLeft(y).ticks(5));

    const defs = svg.append("defs");
    const grad = defs
      .append("linearGradient")
      .attr("id", "radial-time-color")
      .attr("x1", "0%")
      .attr("x2", "0%")
      .attr("y1", "100%")
      .attr("y2", "0%");
    d3.range(0, 1.001, 0.1).forEach((p) => {
      grad
        .append("stop")
        .attr("offset", `${p * 100}%`)
        .attr("stop-color", color(color.domain()[0] + p * (color.domain()[1] - color.domain()[0])));
    });
    svg
      .append("rect")
      .attr("x", W - M.right + 18)
      .attr("y", M.top)
      .attr("width", 14)
      .attr("height", H - M.top - M.bottom)
      .attr("fill", "url(#radial-time-color)");

    svg
      .append("text")
      .attr("x", W / 2)
      .attr("y", H - 4)
      .attr("class", "axis-label")
      .attr("text-anchor", "middle")
      .text("radius (mm)");
    svg
      .append("text")
      .attr("x", 12)
      .attr("y", M.top - 6)
      .attr("class", "axis-label")
      .text("t (s)");
  }, [radialFrames]);

  return (
    <div className="panel mini-graph-panel">
      <div className="panel-head">
        <h2>Temperature Field T(r, t)</h2>
        <span className="muted small">1D radial solver snapshots</span>
      </div>
      <svg
        ref={svgRef}
        className="burn-svg"
        role="img"
        aria-label="Radial temperature field over time"
      />
      {!radialFrames?.length && (
        <p className="muted small">Run a simulation to see the radial time history.</p>
      )}
    </div>
  );
}

function Suggestions({ history, finalData }) {
  const items = React.useMemo(() => {
    if (!history?.length) return [];
    const out = [];
    const last = history[history.length - 1];
    const peak = finalData?.peak_temp_k ?? last?.peak_temp_k ?? 0;
    const burned = last?.fuel_burned_fraction ?? 0;
    const stability = finalData?.stability ?? 0;
    const quenched = finalData?.quenched;
    const growth = (history[history.length - 1]?.max_flame_radius_m ?? 0) - (history[0]?.max_flame_radius_m ?? 0);

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
  }, [history, finalData]);

  if (!items.length) {
    return (
      <div className="panel mini-graph-panel suggestions-panel">
        <h2>Suggestions</h2>
        <p className="muted small">Run a simulation for analysis suggestions.</p>
      </div>
    );
  }

  return (
    <div className="panel mini-graph-panel suggestions-panel">
      <h2>Suggestions</h2>
      <ul className="suggestion-list">
        {items.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ul>
    </div>
  );
}