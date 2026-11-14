import React, { useEffect, useRef, useState } from "react";
import * as d3 from "d3";

/**
 * D3 parameter-space explorer over sweep results.
 * X: swept parameter value. Y: delta score (sim vs NASA PSI disagreement).
 * Color/size: stability. Click a point to run tier-1 triage for that run.
 */
export default function ScatterPlot({ sweepResults, onTriage }) {
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null);

  const results = sweepResults?.results ?? [];

  useEffect(() => {
    if (!results.length) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = 520;
    const H = 240;
    const M = { top: 20, right: 24, bottom: 40, left: 52 };

    const x = d3
      .scaleLinear()
      .domain(d3.extent(results, (d) => d.value) ?? [10, 40])
      .nice()
      .range([M.left, W - M.right]);
    const y = d3
      .scaleLinear()
      .domain([0, 100])
      .range([H - M.bottom, M.top]);
    const c = d3
      .scaleSequential(d3.interpolateRdYlGn)
      .domain([20, 90])
      .clamp(true);

    svg.attr("viewBox", `0 0 ${W} ${H}`);

    svg
      .append("g")
      .attr("transform", `translate(0,${H - M.bottom})`)
      .call(d3.axisBottom(x).ticks(6));
    svg
      .append("g")
      .attr("transform", `translate(${M.left},0)`)
      .call(d3.axisLeft(y).ticks(4).tickFormat((d) => `${d}`));

    svg
      .append("text")
      .attr("x", W / 2)
      .attr("y", H - 6)
      .attr("text-anchor", "middle")
      .attr("class", "axis-label")
      .text(results[0]?.param?.replace(/_/g, " ") ?? "parameter");

    svg
      .append("text")
      .attr("x", 14)
      .attr("y", M.top - 6)
      .attr("class", "axis-label")
      .text("delta score (0-100)");

    const dots = svg
      .append("g")
      .selectAll("circle")
      .data(results)
      .join("circle")
      .attr("cx", (d) => x(d.value))
      .attr("cy", (d) => y(d.verdict?.delta_score ?? 50))
      .attr("r", (d) => 6 + (d.verdict?.stability_score ?? 50) * 0.06)
      .attr("fill", (d) => c(d.verdict?.stability_score ?? 50))
      .attr("fill-opacity", 0.85)
      .attr("stroke", "#14141f")
      .attr("cursor", "pointer")
      .on("pointerenter", (evt, d) => setHover(d))
      .on("pointerleave", () => setHover(null))
      .on("click", (evt, d) => {
        evt.stopPropagation();
        onTriage?.(d.run_id);
      });

    // Quench flags as crosses
    svg
      .append("g")
      .selectAll("path")
      .data(results.filter((d) => d.final?.quenched))
      .join("path")
      .attr(
        "d",
        (d) =>
          `M${x(d.value) - 5},${y(d.verdict?.delta_score ?? 50) - 5}L${x(d.value) + 5},${y(d.verdict?.delta_score ?? 50) + 5}M${x(d.value) - 5},${y(d.verdict?.delta_score ?? 50) + 5}L${x(d.value) + 5},${y(d.verdict?.delta_score ?? 50) - 5}`
      )
      .attr("stroke", "#ff5252")
      .attr("stroke-width", 2)
      .attr("pointer-events", "none");
  }, [results, onTriage]);

  return (
    <div className="panel scatter-panel">
      <div className="panel-head">
        <h2>Parameter Sweep — triage map</h2>
        <span className="muted small">click a point → tier 1 triage</span>
      </div>
      <svg ref={svgRef} className="scatter-svg" role="img" aria-label="Parameter sweep scatter plot" />
      {!results.length && (
        <p className="muted small">
          Run an O₂ sweep to populate the triage map.
        </p>
      )}
      {hover && (
        <div className="hover-card">
          <b>
            {hover.param} = {hover.value}
          </b>
          <br />
          stability {hover.verdict?.stability_score?.toFixed(1)} · delta{" "}
          {hover.verdict?.delta_score?.toFixed(1)} · morphology{" "}
          {hover.verdict?.flame_morphology}
        </div>
      )}
    </div>
  );
}