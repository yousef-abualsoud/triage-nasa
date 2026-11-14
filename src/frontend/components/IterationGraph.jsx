import React, { useEffect, useRef } from "react";
import * as d3 from "d3";

/**
 * Iteration graph: peak temperature and flame radius vs solver iteration
 * (x = iteration / t). Two left/right axes like BurnCurveOverlay.
 */
export default function IterationGraph({ history }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!history?.length) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = 520;
    const H = 220;
    const M = { top: 22, right: 54, bottom: 34, left: 50 };

    const data = history.map((h) => ({
      it: h.iteration ?? 0,
      t: h.t_s,
      temp: h.peak_temp_k,
      r: (h.max_flame_radius_m ?? 0) * 1000,
    }));

    const x = d3
      .scaleLinear()
      .domain(d3.extent(data, (d) => d.it) ?? [0, 1])
      .nice()
      .range([M.left, W - M.right]);
    const tempExtent = d3.extent(data, (d) => d.temp) ?? [300, 2000];
    const yTemp = d3
      .scaleLinear()
      .domain([Math.min(tempExtent[0], 300), tempExtent[1] * 1.05])
      .nice()
      .range([H - M.bottom, M.top]);
    const yR = d3
      .scaleLinear()
      .domain([0, Math.max(d3.max(data, (d) => d.r) * 1.2, 1)])
      .nice()
      .range([H - M.bottom, M.top]);

    svg.attr("viewBox", `0 0 ${W} ${H}`);

    svg
      .append("g")
      .attr("transform", `translate(0,${H - M.bottom})`)
      .call(d3.axisBottom(x).ticks(6));
    svg
      .append("g")
      .attr("transform", `translate(${M.left},0)`)
      .call(d3.axisLeft(yTemp).ticks(5));
    svg
      .append("g")
      .attr("transform", `translate(${W - M.right},0)`)
      .call(d3.axisRight(yR).ticks(4));

    svg
      .append("text")
      .attr("x", W / 2)
      .attr("y", H - 4)
      .attr("class", "axis-label")
      .attr("text-anchor", "middle")
      .text("iteration");
    svg
      .append("text")
      .attr("x", 12)
      .attr("y", M.top - 8)
      .attr("class", "axis-label")
      .text("peak T (K)");
    svg
      .append("text")
      .attr("x", W - 12)
      .attr("y", M.top - 8)
      .attr("class", "axis-label")
      .attr("text-anchor", "end")
      .text("radius (mm)");

    const lineT = d3
      .line()
      .x((d) => x(d.it))
      .y((d) => yTemp(d.temp))
      .curve(d3.curveMonotoneX);
    const lineR = d3
      .line()
      .x((d) => x(d.it))
      .y((d) => yR(d.r))
      .curve(d3.curveMonotoneX);

    svg
      .append("path")
      .datum(data)
      .attr("fill", "none")
      .attr("stroke", "#ff7043")
      .attr("stroke-width", 2)
      .attr("d", lineT);
    svg
      .append("path")
      .datum(data)
      .attr("fill", "none")
      .attr("stroke", "#4dd0e1")
      .attr("stroke-width", 2)
      .attr("d", lineR);
  }, [history]);

  return (
    <div className="panel iter-graph-panel">
      <div className="panel-head">
        <h2>Iteration Graph</h2>
        <span className="legend">
          <i className="sw sim-temp" /> peak T
          <i className="sw sim-rad" /> flame radius
        </span>
      </div>
      <svg ref={svgRef} className="burn-svg" role="img" aria-label="Iteration graph" />
      {!history?.length && (
        <p className="muted small">Run a simulation to see iteration curves.</p>
      )}
    </div>
  );
}