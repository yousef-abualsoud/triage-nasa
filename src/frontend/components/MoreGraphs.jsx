import React, { useEffect, useRef } from "react";
import * as d3 from "d3";

/**
 * Tab 3: additional graphs — soot index & mean temperature history, fuel
 * burned fraction, buoyancy kinetic energy, and the radial temperature
 * profile of the current frame — plus heuristic suggestions read off the
 * run's own numbers (grounded, no external calls).
 */
export default function MoreGraphs({ history, frame, frameIndex, ambientK, finalData }) {
  return (
    <div className="graphs-grid">
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