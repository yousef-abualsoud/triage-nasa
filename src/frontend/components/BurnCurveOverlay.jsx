import React, { useEffect, useRef } from "react";
import * as d3 from "d3";

/**
 * Overlay of C++ predicted curves vs historical NASA flight data.
 * Left axis: peak temperature (K). Right axis: flame radius (mm).
 * Sim history is solid; ground-truth telemetry renders as dashed markers.
 */
export default function BurnCurveOverlay({ simHistory, groundTruth }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!simHistory?.length) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = 520;
    const H = 260;
    const M = { top: 24, right: 56, bottom: 34, left: 52 };

    const tSim = simHistory.map((h) => ({
      t: h.t_s,
      temp: h.peak_temp_k,
      r: (h.max_flame_radius_m ?? 0) * 1000,
    }));

    const tempExtent = d3.extent(tSim, (d) => d.temp) ?? [300, 2000];
    const rExtent = d3.extent(tSim, (d) => d.r) ?? [0, 10];
    const tExtent = d3.extent(tSim, (d) => d.t) ?? [0, 1];

    const x = d3
      .scaleLinear()
      .domain(tExtent)
      .range([M.left, W - M.right]);
    const yTemp = d3
      .scaleLinear()
      .domain([Math.min(tempExtent[0], 300), tempExtent[1] * 1.05])
      .range([H - M.bottom, M.top]);
    const yR = d3
      .scaleLinear()
      .domain([0, Math.max(rExtent[1] * 1.2, 1)])
      .range([H - M.bottom, M.top]);

    svg.attr("viewBox", `0 0 ${W} ${H}`);

    // Grid + axes
    svg
      .append("g")
      .attr("transform", `translate(0,${H - M.bottom})`)
      .call(
        d3
          .axisBottom(x)
          .ticks(5)
          .tickFormat((d) => `${d.toFixed(2)}s`)
      );
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
      .text("time (s)");

    svg
      .append("text")
      .attr("x", 14)
      .attr("y", M.top + 2)
      .attr("class", "axis-label")
      .text("peak T (K)");

    svg
      .append("text")
      .attr("x", W - 14)
      .attr("y", M.top + 2)
      .attr("class", "axis-label")
      .attr("text-anchor", "end")
      .text("radius (mm)");

    // Sim temperature curve (solid)
    const lineT = d3
      .line()
      .x((d) => x(d.t))
      .y((d) => yTemp(d.temp))
      .curve(d3.curveMonotoneX);
    svg
      .append("path")
      .datum(tSim)
      .attr("fill", "none")
      .attr("stroke", "#ff7043")
      .attr("stroke-width", 2)
      .attr("d", lineT);

    // Sim radius curve (solid, right axis)
    const lineR = d3
      .line()
      .x((d) => x(d.t))
      .y((d) => yR(d.r))
      .curve(d3.curveMonotoneX);
    svg
      .append("path")
      .datum(tSim)
      .attr("fill", "none")
      .attr("stroke", "#4dd0e1")
      .attr("stroke-width", 2)
      .attr("d", lineR);

    // Ground truth overlays when available (dashed + circles)
    if (groundTruth?.profile_t?.length) {
      const gtTimes = groundTruth.profile_r?.length
        ? d3.range(groundTruth.profile_t.length).map(
            (i) =>
              (tExtent[1] * i) /
              Math.max(groundTruth.profile_t.length - 1, 1)
          )
        : [];
      const gtPairs = groundTruth.profile_t.map((temp, i) => ({
        t: gtTimes[i] ?? tExtent[1],
        temp,
        r: groundTruth.profile_r?.[i] ?? 0,
      }));
      const lineGT = d3
        .line()
        .x((d) => x(d.t))
        .y((d) => yTemp(d.temp))
        .curve(d3.curveMonotoneX);
      svg
        .append("path")
        .datum(gtPairs)
        .attr("fill", "none")
        .attr("stroke", "#bcaaa4")
        .attr("stroke-dasharray", "5 4")
        .attr("stroke-width", 1.6)
        .attr("d", lineGT);
      svg
        .append("g")
        .selectAll("circle")
        .data(gtPairs)
        .join("circle")
        .attr("cx", (d) => x(d.t))
        .attr("cy", (d) => yTemp(d.temp))
        .attr("r", 2.6)
        .attr("fill", "#ffccbc")
        .attr("stroke", "#5d4037");
    }
  }, [simHistory, groundTruth]);

  return (
    <div className="panel curve-panel">
      <div className="panel-head">
        <h2>Burn Curves — sim vs NASA flight data</h2>
        <span className="legend">
          <i className="sw sim-temp" /> sim peak T
          <i className="sw sim-rad" /> sim radius
          <i className="sw gt" /> NASA PSI telemetry
        </span>
      </div>
      <svg ref={svgRef} className="burn-svg" role="img" aria-label="Burn curve overlay" />
      {!simHistory?.length && (
        <p className="muted small">Run a simulation to populate the overlay.</p>
      )}
    </div>
  );
}