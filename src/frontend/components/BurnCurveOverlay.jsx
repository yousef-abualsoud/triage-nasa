import React, { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import ChartTooltip from "./ChartTooltip.jsx";
import {
  CHART_M,
  addAxes,
  addAxisTitles,
  addGrid,
  nearestValueIndex,
  placeTooltip,
  useChartWidth,
} from "./chartUtils.js";

/**
 * Overlay of C++ predicted curves vs historical NASA flight data.
 * Left axis: peak temperature (K). Right axis: flame radius (mm).
 * Sim history is solid; ground-truth telemetry renders as dashed markers.
 */
export default function BurnCurveOverlay({ simHistory, groundTruth }) {
  const svgRef = useRef(null);
  const [wrapRef, measured] = useChartWidth();
  const [hover, setHover] = useState(null);
  const hasGtProfile = Boolean(groundTruth?.profile_t?.length);

  useEffect(() => {
    if (!simHistory?.length || !svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = measured || 760;
    const H = 300;
    const m = { ...CHART_M, top: 20 };
    svg.attr("viewBox", `0 0 ${W} ${H}`);

    const tSim = simHistory
      .map((h) => ({
        t: h.t_s ?? 0,
        temp: h.peak_temp_k,
        r: (h.max_flame_radius_m ?? 0) * 1000,
      }))
      .filter((d) => d.temp != null);
    if (!tSim.length) return;

    // Time series start at t=0, matching the solver's initial saved state.
    const tMax = d3.max(tSim, (d) => d.t) || 1;
    const x = d3
      .scaleLinear()
      .domain([0, tMax])
      .nice()
      .range([m.left, W - m.right]);

    const tempExtent = d3.extent(tSim, (d) => d.temp);
    const yTemp = d3
      .scaleLinear()
      .domain([
        Math.min(tempExtent[0], 300),
        Math.max(tempExtent[1] * 1.05, tempExtent[0] + 1),
      ])
      .nice()
      .range([H - m.bottom, m.top]);
    const rExtent = d3.extent(tSim, (d) => d.r) ?? [0, 1];
    const yR = d3
      .scaleLinear()
      .domain([0, Math.max(rExtent[1] * 1.15, 1)])
      .nice()
      .range([H - m.bottom, m.top]);

    svg.attr("viewBox", `0 0 ${W} ${H}`);
    addGrid(svg, { W, H, x, y: yTemp, m, xTicks: 5, yTicks: 5 });
    addAxes(svg, {
      W,
      H,
      x,
      y: yTemp,
      m,
      xTicks: 5,
      yTicks: 5,
      xFormat: (d) => d.toFixed(2),
      yFormat: d3.format(",.0f"),
    });
    svg
      .append("g")
      .attr("class", "axis axis-y axis-y-right")
      .attr("transform", `translate(${W - m.right},0)`)
      .call(
        d3.axisRight(yR).ticks(4).tickPadding(7).tickFormat(d3.format(".0f"))
      );
    addAxisTitles(svg, {
      W,
      H,
      m,
      x: "time (s)",
      y: "peak T (K)",
      yRight: "radius (mm)",
    });

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
      .attr("stroke-linecap", "round")
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
      .attr("stroke-linecap", "round")
      .attr("d", lineR);

    // Ground truth overlays when available (dashed + circles)
    if (groundTruth?.profile_t?.length) {
      const gtTimes = groundTruth.profile_r?.length
        ? d3.range(groundTruth.profile_t.length).map(
            (i) => (tMax * i) / Math.max(groundTruth.profile_t.length - 1, 1)
          )
        : [];
      const gtPairs = groundTruth.profile_t.map((temp, i) => ({
        t: gtTimes[i] ?? tMax,
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

    const tValues = tSim.map((d) => d.t);
    const focus = svg.append("g").attr("class", "hover-focus").style("display", "none");
    const crosshair = focus
      .append("line")
      .attr("class", "hover-crosshair")
      .attr("y1", m.top)
      .attr("y2", H - m.bottom);
    const dotT = focus.append("circle").attr("r", 3.4).attr("fill", "#ff7043");
    const dotR = focus.append("circle").attr("r", 3.4).attr("fill", "#4dd0e1");
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
        const index = nearestValueIndex(tValues, x.invert(px));
        const point = tSim[index];
        const cx = x(point.t);
        const ty = yTemp(point.temp);
        const ry = yR(point.r);
        focus.style("display", null);
        crosshair.attr("x1", cx).attr("x2", cx);
        dotT.attr("cx", cx).attr("cy", ty);
        dotR.attr("cx", cx).attr("cy", ry);
        setHover({
          ...placeTooltip(cx, Math.min(ty, ry), W, H),
          title: `x = ${point.t.toFixed(4)} s`,
          rows: [
            {
              label: "peak T",
              value: `${d3.format(",.1f")(point.temp)} K`,
              color: "#ff7043",
            },
            {
              label: "radius",
              value: `${d3.format(",.2f")(point.r)} mm`,
              color: "#4dd0e1",
            },
          ],
        });
      })
      .on("pointerleave", () => {
        focus.style("display", "none");
        setHover(null);
      });
  }, [simHistory, groundTruth, measured]);

  return (
    <div className="panel curve-panel">
      <div className="panel-head">
        <h2>Burn Curves — sim vs NASA flight data</h2>
        <span className="legend">
          <i className="sw sim-temp" /> sim peak T
          <i className="sw sim-rad" /> sim radius
          {hasGtProfile && (
            <>
              <i className="sw gt" /> NASA PSI telemetry
            </>
          )}
        </span>
      </div>
      <div className="chart-wrap" ref={wrapRef}>
        <svg
          ref={svgRef}
          className="chart-svg"
          data-chart="burn-curves"
          role="img"
          aria-label="Burn curve overlay"
        />
        <ChartTooltip hover={hover} />
      </div>
      {!simHistory?.length && (
        <p className="muted small">Run a simulation to populate the overlay.</p>
      )}
      {groundTruth && !hasGtProfile && (
        <p className="muted small chart-note">
          {groundTruth.investigation || "NASA PSI"}{" "}
          {groundTruth.test_point || ""} carries flows, ion current and PMT
          telemetry, not a radius/temperature series — compare its conditions
          and burn duration in the Jev panel.
        </p>
      )}
    </div>
  );
}
