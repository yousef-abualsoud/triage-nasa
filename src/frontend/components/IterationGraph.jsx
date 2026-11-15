import React, { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import ChartTooltip from "./ChartTooltip.jsx";
import {
  CHART_M,
  addAxes,
  addAxisTitles,
  addGrid,
  autoFormat,
  nearestValueIndex,
  placeTooltip,
  useChartWidth,
} from "./chartUtils.js";

/**
 * Iteration graph: peak-temperature change between output samples.
 * ΔT = T₂ − T₁, where T₂ is the current saved iteration's peak temperature
 * and T₁ is the previous one (zero on the first point).
 */
export default function IterationGraph({ history }) {
  const [wrapRef, measured] = useChartWidth();
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null);

  useEffect(() => {
    if (!history?.length || !svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = measured || 760;
    const H = 214;
    const m = { ...CHART_M, right: 30 };

    const data = history
      .map((h, i) => {
        const iteration = h.iteration ?? i;
        const t2 = h.peak_temp_k;
        const t1 = i === 0 ? 0 : history[i - 1]?.peak_temp_k ?? 0;
        return { iteration, t1, t2, delta: (t2 ?? 0) - t1 };
      })
      .filter((d) => d.t2 != null);
    if (!data.length) return;

    const maxIter = d3.max(data, (d) => d.iteration) || 1;
    const x = d3
      .scaleLinear()
      .domain([0, maxIter])
      .nice()
      .range([m.left, W - m.right]);

    const ext = d3.extent(data, (d) => d.delta);
    const lo = Math.min(ext[0] ?? 0, 0);
    const hi = Math.max(ext[1] ?? 0, 1);
    const y = d3
      .scaleLinear()
      .domain([lo, hi])
      .nice()
      .range([H - m.bottom, m.top]);

    svg.attr("viewBox", `0 0 ${W} ${H}`);
    addGrid(svg, { W, H, x, y, m, xTicks: 5, yTicks: 5 });
    addAxes(svg, {
      W,
      H,
      x,
      y,
      m,
      xTicks: 5,
      yTicks: 5,
      xFormat: d3.format("d"),
      yFormat: autoFormat,
    });
    addAxisTitles(svg, { W, H, m, x: "iteration", y: "ΔT (K)" });

    svg
      .append("line")
      .attr("class", "chart-zero")
      .attr("x1", m.left)
      .attr("x2", W - m.right)
      .attr("y1", y(0))
      .attr("y2", y(0));

    const line = d3
      .line()
      .x((d) => x(d.iteration))
      .y((d) => y(d.delta))
      .curve(d3.curveMonotoneX);
    svg
      .append("path")
      .datum(data)
      .attr("fill", "none")
      .attr("stroke", "#ff7043")
      .attr("stroke-width", 2)
      .attr("stroke-linecap", "round")
      .attr("stroke-linejoin", "round")
      .attr("d", line);

    const focus = svg.append("g").attr("class", "hover-focus").style("display", "none");
    const crosshair = focus
      .append("line")
      .attr("class", "hover-crosshair")
      .attr("y1", m.top)
      .attr("y2", H - m.bottom);
    const dot = focus.append("circle").attr("r", 3.6).attr("fill", "#ff7043");
    svg
      .append("rect")
      .attr("class", "hover-layer")
      .attr("x", m.left)
      .attr("y", m.top)
      .attr("width", Math.max(W - m.left - m.right, 1))
      .attr("height", Math.max(H - m.top - m.bottom, 1))
      .attr("fill", "transparent")
      .on("pointermove", (event) => {
        const [px] = d3.pointer(event, svg.node());
        const index = nearestValueIndex(
          data.map((d) => d.iteration),
          x.invert(px)
        );
        const point = data[index];
        const cx = x(point.iteration);
        const cy = y(point.delta);
        focus.style("display", null);
        crosshair.attr("x1", cx).attr("x2", cx);
        dot.attr("cx", cx).attr("cy", cy);
        setHover({
          ...placeTooltip(cx, cy, W, H),
          title: `x = iteration ${point.iteration}`,
          rows: [
            {
              label: "ΔT",
              value: `${d3.format(",.1f")(point.delta)} K`,
              color: "#ff7043",
            },
            {
              label: "T₂",
              value: `${d3.format(",.1f")(point.t2)} K`,
            },
            {
              label: "T₁",
              value: `${d3.format(",.1f")(point.t1)} K`,
            },
          ],
        });
      })
      .on("pointerleave", () => {
        focus.style("display", "none");
        setHover(null);
      });
  }, [history, measured]);

  return (
    <div className="panel mini-graph-panel iter-graph-panel">
      <div className="panel-head">
        <h2>Iteration Graph</h2>
        <span className="legend">
          <i className="sw" style={{ background: "#ff7043" }} /> ΔT (K)
        </span>
      </div>
      <div className="chart-wrap" ref={wrapRef}>
        <svg
          ref={svgRef}
          className="chart-svg"
          data-chart="iteration-delta-t"
          role="img"
          aria-label="Peak temperature change per iteration"
        />
        <ChartTooltip hover={hover} />
      </div>
      {!history?.length && (
        <p className="muted small">Run a simulation to see iteration deltas.</p>
      )}
    </div>
  );
}
