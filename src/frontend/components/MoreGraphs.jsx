import React, { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import BurnCurveOverlay from "./BurnCurveOverlay.jsx";
import ChartTooltip from "./ChartTooltip.jsx";
import IterationGraph from "./IterationGraph.jsx";
import { buildSuggestions } from "../diagnostics.js";
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

const PERCENT = d3.format(".0%");

/** Hold the innermost solver value down to the r=0 axis for a closed profile. */
function extendToOrigin(values) {
  return values?.length ? [values[0], ...values] : values;
}

const SOOT_SERIES = [
  {
    key: "soot_index",
    label: "soot index",
    color: "#b0a8ff",
    axis: "left",
    axisTitle: "soot index",
    format: d3.format(".2f"),
  },
  {
    key: "mean_temp_k",
    label: "mean T (K)",
    color: "#ff9e40",
    axis: "right",
    axisTitle: "T (K)",
    format: d3.format(",.0f"),
  },
];

const BURNED_SERIES = [
  {
    key: "fuel_burned_fraction",
    label: "burned fuel",
    color: "#66bb6a",
    scale: [0, 1],
    axisTitle: "fuel burned",
    format: PERCENT,
  },
];

/**
 * Tab 3: run diagnostics — burn curves vs NASA PSI telemetry, radial solver
 * fields, species profiles, T(r,t), history trends, and rule-based suggestions.
 * Every chart measures its container and renders at CSS pixel size, so labels
 * stay legible instead of being scaled up with the SVG.
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
  const last = history?.length ? history[history.length - 1] : null;
  const peakTemp = finalData?.peak_temp_k ?? last?.peak_temp_k ?? null;
  const burned = last?.fuel_burned_fraction ?? null;
  const radiusM = last?.max_flame_radius_m ?? finalData?.max_flame_radius_m ?? null;
  const endTime = last?.t_s ?? null;

  return (
    <div className="graphs-dashboard">
      <header className="graphs-header">
        <div className="graphs-heading">
          <h2>Run diagnostics</h2>
          <p className="muted small">
            Radial solver fields, species transport, and the NASA PSI burn
            comparison for this run.
          </p>
        </div>
        {history?.length ? (
          <div className="graphs-kpis" aria-label="Run summary">
            <Kpi
              label="Peak temperature"
              value={
                peakTemp != null
                  ? `${Math.round(peakTemp).toLocaleString()} K`
                  : "—"
              }
            />
            <Kpi
              label="Fuel burned"
              value={burned != null ? `${Math.round(burned * 100)}%` : "—"}
            />
            <Kpi
              label="Flame radius"
              value={radiusM != null ? `${(radiusM * 1000).toFixed(1)} mm` : "—"}
            />
            <Kpi
              label="Run time"
              value={endTime != null ? `${endTime.toFixed(2)} s` : "—"}
            />
          </div>
        ) : null}
      </header>

      <div className="graphs-hero">
        <BurnCurveOverlay simHistory={history} groundTruth={groundTruth} />
        <Suggestions history={history} finalData={finalData} />
      </div>

      <div className="graphs-row graphs-row-3">
        <SolverRadialFields finalRadial={finalRadial} />
        <SpeciesProfile finalRadial={finalRadial} />
        <RadialProfile
          frame={frame}
          frameIndex={frameIndex}
          ambientK={ambientK}
        />
      </div>

      <RadialTimeHeatmap radialFrames={radialFrames} />

      <div className="graphs-row graphs-row-3">
        <HistoryGraph
          history={history}
          series={SOOT_SERIES}
          title="Soot & Mean Temperature"
          aria="Soot index and mean temperature history"
          chartKey="history-soot"
        />
        <HistoryGraph
          history={history}
          series={BURNED_SERIES}
          title="Fuel Burned Fraction"
          aria="Fuel burned fraction over iterations"
          chartKey="history-burned"
        />
        <IterationGraph history={history} />
      </div>
    </div>
  );
}

function Kpi({ label, value }) {
  return (
    <div className="graph-kpi">
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

function HistoryGraph({ history, series, title, aria, chartKey, height = 214 }) {
  const [wrapRef, measured] = useChartWidth();
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null);

  useEffect(() => {
    if (!history?.length || !svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = measured || 430;
    const H = height;
    const m = {
      ...CHART_M,
      right: series.some((s) => s.axis === "right") ? 74 : 26,
    };
    svg.attr("viewBox", `0 0 ${W} ${H}`);

    // Both history styles start their x axis at the run origin (iteration 0).
    const maxIter = d3.max(history, (h, i) => h.iteration ?? i) || 1;
    const x = d3
      .scaleLinear()
      .domain([0, maxIter])
      .nice()
      .range([m.left, W - m.right]);

    const sideOf = (s) => (s.axis === "right" ? "right" : "left");
    const scales = {};
    ["left", "right"]
      .filter((side) => series.some((s) => sideOf(s) === side))
      .forEach((side) => {
        let lo = Infinity;
        let hi = -Infinity;
        let auto = false;
        series
          .filter((s) => sideOf(s) === side)
          .forEach((s) => {
            if (Array.isArray(s.scale)) {
              lo = Math.min(lo, s.scale[0]);
              hi = Math.max(hi, s.scale[1]);
            } else {
              const vals = history.map((h) => h[s.key]).filter((v) => v != null);
              if (!vals.length) return;
              const ext = d3.extent(vals);
              lo = Math.min(lo, Math.min(ext[0], 0));
              hi = Math.max(hi, ext[1]);
              auto = true;
            }
          });
        if (!Number.isFinite(lo) || !Number.isFinite(hi)) {
          lo = 0;
          hi = 1;
        }
        if (hi <= lo) hi = lo + 1;
        if (auto && hi > 0) hi *= 1.08;
        scales[side] = d3
          .scaleLinear()
          .domain([lo, hi])
          .nice()
          .range([H - m.bottom, m.top]);
      });

    const primary = scales.left ?? scales.right;
    const leftSeries = series.find((s) => sideOf(s) === "left");
    const rightSeries = series.find((s) => sideOf(s) === "right");

    addGrid(svg, { W, H, x, y: primary, m, xTicks: 5, yTicks: 4 });
    addAxes(svg, {
      W,
      H,
      x,
      y: primary,
      m,
      xTicks: 5,
      yTicks: 4,
      yFormat: leftSeries?.format ?? autoFormat,
    });
    if (scales.right) {
      svg
        .append("g")
        .attr("class", "axis axis-y axis-y-right")
        .attr("transform", `translate(${W - m.right},0)`)
        .call(
          d3
            .axisRight(scales.right)
            .ticks(4)
            .tickPadding(7)
            .tickFormat(rightSeries?.format ?? autoFormat)
        );
    }
    addAxisTitles(svg, {
      W,
      H,
      m,
      x: "iteration",
      y: leftSeries?.axisTitle,
      yRight: scales.right ? rightSeries?.axisTitle : undefined,
    });

    series.forEach((s) => {
      const y = scales[sideOf(s)];
      const line = d3
        .line()
        .defined((h) => h[s.key] != null)
        .x((h, i) => x(h.iteration ?? i))
        .y((h) => y(h[s.key]))
        .curve(d3.curveMonotoneX);
      svg
        .append("path")
        .datum(history)
        .attr("fill", "none")
        .attr("stroke", s.color)
        .attr("stroke-width", 2)
        .attr("stroke-linecap", "round")
        .attr("stroke-linejoin", "round")
        .attr("d", line);
    });

    const iterations = history.map((h, i) => h.iteration ?? i);
    const focus = svg.append("g").attr("class", "hover-focus").style("display", "none");
    const crosshair = focus
      .append("line")
      .attr("class", "hover-crosshair")
      .attr("y1", m.top)
      .attr("y2", H - m.bottom);
    const dots = series.map((s) =>
      focus.append("circle").attr("r", 3.4).attr("fill", s.color)
    );
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
        const index = nearestValueIndex(iterations, x.invert(px));
        const row = history[index];
        const cx = x(iterations[index]);
        focus.style("display", null);
        crosshair.attr("x1", cx).attr("x2", cx);
        const ys = [];
        const rows = series.map((s, i) => {
          const value = row[s.key];
          if (value == null) {
            dots[i].attr("r", 0);
            return null;
          }
          const cy = scales[sideOf(s)](value);
          ys.push(cy);
          dots[i].attr("r", 3.4).attr("cx", cx).attr("cy", cy);
          return {
            label: s.label,
            value: (s.format ?? autoFormat)(value),
            color: s.color,
          };
        }).filter(Boolean);
        if (!rows.length) return;
        setHover({
          ...placeTooltip(cx, Math.min(...ys), W, H),
          title: `x = iteration ${iterations[index]}`,
          rows,
        });
      })
      .on("pointerleave", () => {
        focus.style("display", "none");
        setHover(null);
      });
  }, [history, series, measured, height]);

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
      <div className="chart-wrap" ref={wrapRef}>
        <svg
          ref={svgRef}
          className="chart-svg"
          data-chart={chartKey}
          role="img"
          aria-label={aria}
        />
        <ChartTooltip hover={hover} />
      </div>
      {!history?.length && (
        <p className="muted small">Run a simulation to populate this graph.</p>
      )}
    </div>
  );
}

function RadialProfile({ frame, frameIndex, ambientK }) {
  const [wrapRef, measured] = useChartWidth();
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null);

  useEffect(() => {
    if (!frame?.length || !svgRef.current) return;
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
          // First/last bins sit on the axis edges so the profile spans 0–100%.
          r: bins > 1 ? b / (bins - 1) : 0,
          temp: sums[b] / counts[b],
        });
      }
    }

    const W = measured || 430;
    const H = 218;
    const m = { ...CHART_M, right: 26 };
    const x = d3.scaleLinear().domain([0, 1]).range([m.left, W - m.right]);
    const temps = data.map((d) => d.temp);
    const y = d3
      .scaleLinear()
      .domain([
        Math.min(ambientK ?? 300, d3.min(temps) ?? 300),
        Math.max((d3.max(temps) ?? 2500) * 1.05, (d3.min(temps) ?? 300) + 1),
      ])
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
      xFormat: (d) => `${Math.round(d * 100)}%`,
      yFormat: autoFormat,
    });
    addAxisTitles(svg, {
      W,
      H,
      m,
      x: "radius (% of domain)",
      y: "T (K)",
    });

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
      .attr("stroke-linecap", "round")
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
          data.map((d) => d.r),
          x.invert(px)
        );
        const point = data[index];
        const cx = x(point.r);
        const cy = y(point.temp);
        focus.style("display", null);
        crosshair.attr("x1", cx).attr("x2", cx);
        dot.attr("cx", cx).attr("cy", cy);
        setHover({
          ...placeTooltip(cx, cy, W, H),
          title: `x = ${(point.r * 100).toFixed(0)}%`,
          rows: [
            {
              label: "T",
              value: `${d3.format(",.1f")(point.temp)} K`,
              color: "#ff7043",
            },
          ],
        });
      })
      .on("pointerleave", () => {
        focus.style("display", "none");
        setHover(null);
      });
  }, [frame, frameIndex, ambientK, measured]);

  return (
    <div className="panel mini-graph-panel">
      <div className="panel-head">
        <h2>Radial Temperature Profile</h2>
        <span className="muted small">current frame, angle-averaged</span>
      </div>
      <div className="chart-wrap" ref={wrapRef}>
        <svg
          ref={svgRef}
          className="chart-svg"
          data-chart="radial-temperature"
          role="img"
          aria-label="Radial temperature profile"
        />
        <ChartTooltip hover={hover} />
      </div>
      {!frame?.length && (
        <p className="muted small">Run a simulation to see the radial profile.</p>
      )}
    </div>
  );
}

function SolverRadialFields({ finalRadial }) {
  const [wrapRef, measured] = useChartWidth();
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null);

  useEffect(() => {
    if (!finalRadial?.r_m?.length || !svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = measured || 430;
    const H = 218;
    const m = { ...CHART_M, right: 74 };
    const r = finalRadial.r_m.map((v) => v * 1000);
    const T = finalRadial.temperature_k;
    const q = finalRadial.heat_release_w_m3;
    // The solver domain starts at r_min; hold the innermost values down to
    // the 0 axis so the plotted profile touches x=0 like the axis does.
    const rPlot = [0, ...r];
    const TPlot = extendToOrigin(T);
    const qPlot = extendToOrigin(q);
    const x = d3
      .scaleLinear()
      .domain([0, d3.max(r) || 1])
      .nice()
      .range([m.left, W - m.right]);
    const y = d3
      .scaleLinear()
      .domain([
        Math.min(d3.min(T), 250) * 0.95,
        Math.max(d3.max(T) * 1.05, d3.min(T) + 1),
      ])
      .nice()
      .range([H - m.bottom, m.top]);
    const qMax = Math.max(d3.max(q) || 1, 1);
    // Linear right axis: every tick is equidistant, matching the left axis's
    // tick count and vertical positions. Exact peaks are read from the hover
    // tooltip rather than by crowding labels at the top of a symlog axis.
    const yq = d3
      .scaleLinear()
      .domain([0, qMax])
      .range([H - m.bottom, m.top]);
    const qTicks = y.ticks(5).map((tickValue) => yq.invert(y(tickValue)));

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
      yFormat: autoFormat,
    });
    svg
      .append("g")
      .attr("class", "axis axis-y axis-y-right")
      .attr("transform", `translate(${W - m.right},0)`)
      .call(
        d3
          .axisRight(yq)
          .tickValues(qTicks)
          .tickPadding(7)
          .tickFormat((v) => (v === 0 ? "0" : d3.format(".2s")(v)))
      );
    addAxisTitles(svg, {
      W,
      H,
      m,
      x: "radius (mm)",
      y: "T (K)",
      yRight: "q̇ (W/m³)",
    });

    // Mark where the simulated domain actually begins (between 0 and r_min
    // the innermost value is a display extension, not a solved cell).
    svg
      .append("line")
      .attr("class", "chart-boundary")
      .attr("x1", x(r[0]))
      .attr("x2", x(r[0]))
      .attr("y1", m.top)
      .attr("y2", H - m.bottom)
      .append("title")
      .text(`Solver inner boundary r_min = ${r[0].toFixed(2)} mm`);

    const lineT = d3
      .line()
      .x((_, i) => x(rPlot[i]))
      .y((v) => y(v))
      .curve(d3.curveMonotoneX);
    svg
      .append("path")
      .datum(TPlot)
      .attr("fill", "none")
      .attr("stroke", "#ff7043")
      .attr("stroke-width", 2)
      .attr("stroke-linecap", "round")
      .attr("d", lineT);

    const lineQ = d3
      .line()
      .x((_, i) => x(rPlot[i]))
      .y((v) => yq(v))
      .curve(d3.curveMonotoneX);
    svg
      .append("path")
      .datum(qPlot)
      .attr("fill", "none")
      .attr("stroke", "#66bb6a")
      .attr("stroke-width", 1.5)
      .attr("stroke-dasharray", "4 3")
      .attr("d", lineQ);

    const focus = svg.append("g").attr("class", "hover-focus").style("display", "none");
    const crosshair = focus
      .append("line")
      .attr("class", "hover-crosshair")
      .attr("y1", m.top)
      .attr("y2", H - m.bottom);
    const dotT = focus.append("circle").attr("r", 3.4).attr("fill", "#ff7043");
    const dotQ = focus.append("circle").attr("r", 3.4).attr("fill", "#66bb6a");
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
        const index = nearestValueIndex(rPlot, x.invert(px));
        const cx = x(rPlot[index]);
        const ty = y(TPlot[index]);
        const qy = yq(qPlot[index]);
        focus.style("display", null);
        crosshair.attr("x1", cx).attr("x2", cx);
        dotT.attr("cx", cx).attr("cy", ty);
        dotQ.attr("cx", cx).attr("cy", qy);
        const qValue = Number(qPlot[index]);
        setHover({
          ...placeTooltip(cx, Math.min(ty, qy), W, H),
          title: `x = ${rPlot[index].toFixed(2)} mm`,
          rows: [
            { label: "T", value: `${d3.format(",.1f")(TPlot[index])} K`, color: "#ff7043" },
            {
              label: "q̇",
              value: `${qValue === 0 ? "0" : qValue.toExponential(3)} W/m³`,
              color: "#66bb6a",
            },
          ],
        });
      })
      .on("pointerleave", () => {
        focus.style("display", "none");
        setHover(null);
      });
  }, [finalRadial, measured]);

  return (
    <div className="panel mini-graph-panel">
      <div className="panel-head">
        <h2>Solver Radial Fields</h2>
        <span className="legend">
          <i className="sw" style={{ background: "#ff7043" }} /> T (left)
          <i className="sw" style={{ background: "#66bb6a" }} /> q̇ (right)
        </span>
      </div>
      <div className="chart-wrap" ref={wrapRef}>
        <svg
          ref={svgRef}
          className="chart-svg"
          data-chart="solver-radial"
          role="img"
          aria-label="Radial temperature and heat-release profiles"
        />
        <ChartTooltip hover={hover} />
      </div>
      {!finalRadial?.r_m?.length && (
        <p className="muted small">
          Run a simulation to see the solver radial fields.
        </p>
      )}
      {finalRadial?.r_m?.length ? (
        <p className="muted small chart-hint">
          r &lt; {(finalRadial.r_m[0] * 1000).toFixed(2)} mm: inner-boundary
          value held constant (solver domain starts at r_min).
        </p>
      ) : null}
    </div>
  );
}

function SpeciesProfile({ finalRadial }) {
  const [wrapRef, measured] = useChartWidth();
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null);

  useEffect(() => {
    if (!finalRadial?.mass_fractions || !svgRef.current) return;
    const keys = Object.keys(finalRadial.mass_fractions);
    if (!keys.length) return;
    const fuelKey = keys[0];
    const o2Key = keys.find((k) => k === "O2");
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = measured || 430;
    const H = 218;
    const m = { ...CHART_M, right: 26 };
    const r = finalRadial.r_m.map((v) => v * 1000);
    const rPlot = [0, ...r];
    const series = [
      {
        key: fuelKey,
        label: fuelKey,
        color: "#ffb74d",
        values: finalRadial.mass_fractions[fuelKey],
      },
      ...(o2Key
        ? [
            {
              key: o2Key,
              label: o2Key,
              color: "#4dd0e1",
              values: finalRadial.mass_fractions[o2Key],
            },
          ]
        : []),
    ];
    const x = d3
      .scaleLinear()
      .domain([0, d3.max(r) || 1])
      .nice()
      .range([m.left, W - m.right]);
    const ymax = Math.max(
      0.05,
      d3.max(series, (s) => d3.max(s.values)) * 1.1
    );
    const y = d3
      .scaleLinear()
      .domain([0, ymax])
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
      yFormat: autoFormat,
    });
    addAxisTitles(svg, {
      W,
      H,
      m,
      x: "radius (mm)",
      y: "mass fraction",
    });

    svg
      .append("line")
      .attr("class", "chart-boundary")
      .attr("x1", x(r[0]))
      .attr("x2", x(r[0]))
      .attr("y1", m.top)
      .attr("y2", H - m.bottom)
      .append("title")
      .text(`Solver inner boundary r_min = ${r[0].toFixed(2)} mm`);

    series.forEach((s) => {
      const values = extendToOrigin(s.values);
      const line = d3
        .line()
        .x((_, i) => x(rPlot[i]))
        .y((v) => y(v))
        .curve(d3.curveMonotoneX);
      svg
        .append("path")
        .datum(values)
        .attr("fill", "none")
        .attr("stroke", s.color)
        .attr("stroke-width", 2)
        .attr("stroke-linecap", "round")
        .attr("d", line);
    });

    const plotSeries = series.map((s) => ({
      ...s,
      plot: extendToOrigin(s.values),
    }));
    const focus = svg.append("g").attr("class", "hover-focus").style("display", "none");
    const crosshair = focus
      .append("line")
      .attr("class", "hover-crosshair")
      .attr("y1", m.top)
      .attr("y2", H - m.bottom);
    const dots = plotSeries.map((s) =>
      focus.append("circle").attr("r", 3.4).attr("fill", s.color)
    );
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
        const index = nearestValueIndex(rPlot, x.invert(px));
        const cx = x(rPlot[index]);
        focus.style("display", null);
        crosshair.attr("x1", cx).attr("x2", cx);
        const ys = plotSeries.map((s, i) => {
          const cy = y(s.plot[index]);
          dots[i].attr("cx", cx).attr("cy", cy);
          return cy;
        });
        setHover({
          ...placeTooltip(cx, Math.min(...ys), W, H),
          title: `x = ${rPlot[index].toFixed(2)} mm`,
          rows: plotSeries.map((s) => ({
            label: s.label,
            value: d3.format(".5f")(s.plot[index]),
            color: s.color,
          })),
        });
      })
      .on("pointerleave", () => {
        focus.style("display", "none");
        setHover(null);
      });
  }, [finalRadial, measured]);

  const keys = finalRadial?.mass_fractions
    ? Object.keys(finalRadial.mass_fractions)
    : [];
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
      <div className="chart-wrap" ref={wrapRef}>
        <svg
          ref={svgRef}
          className="chart-svg"
          data-chart="species"
          role="img"
          aria-label="Fuel and oxygen mass-fraction profiles"
        />
        <ChartTooltip hover={hover} />
      </div>
      {!keys.length && (
        <p className="muted small">
          Run a simulation to see species profiles.
        </p>
      )}
      {keys.length ? (
        <p className="muted small chart-hint">
          r &lt; {(finalRadial.r_m[0] * 1000).toFixed(2)} mm: inner-boundary
          value held constant (solver domain starts at r_min).
        </p>
      ) : null}
    </div>
  );
}

function RadialTimeHeatmap({ radialFrames }) {
  const [wrapRef, measured] = useChartWidth();
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null);

  useEffect(() => {
    if (!radialFrames?.length || !svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = measured || 860;
    const H = 250;
    const m = { ...CHART_M, top: 20, right: 100 };
    const r = radialFrames[0].r_m.map((v) => v * 1000);
    const times = radialFrames.map((f) => f.t_s);
    const allT = radialFrames.flatMap((f) => f.temperature_k);
    const x = d3
      .scaleLinear()
      .domain([0, d3.max(r) || 1])
      .nice()
      .range([m.left, W - m.right]);
    const tMax = d3.max(times) || 1;
    const y = d3
      .scaleLinear()
      .domain([0, tMax])
      .nice()
      .range([H - m.bottom, m.top]);
    const color = d3
      .scaleSequential(d3.interpolateInferno)
      .domain([d3.min(allT) ?? 300, d3.max(allT) ?? 3000]);

    svg.attr("viewBox", `0 0 ${W} ${H}`);
    const clipId = "radial-time-clip";
    svg
      .append("defs")
      .append("clipPath")
      .attr("id", clipId)
      .append("rect")
      .attr("x", m.left)
      .attr("y", m.top)
      .attr("width", W - m.left - m.right)
      .attr("height", H - m.top - m.bottom);

    const cells = svg.append("g").attr("clip-path", `url(#${clipId})`);
    // Edges from midpoints between actual samples: the coarse radial grid is
    // mostly 4 cells but occasionally 5, so a fixed step leaves black bands.
    const edge = (values, i) => {
      if (values.length === 1) return i === 0 ? [0, values[0] * 2] : [values[0], 0];
      if (i === 0) return [Math.max(0, values[0] - (values[1] - values[0]) / 2), (values[0] + values[1]) / 2];
      if (i === values.length - 1) {
        return [(values[i - 1] + values[i]) / 2, values[i] + (values[i] - values[i - 1]) / 2];
      }
      return [(values[i - 1] + values[i]) / 2, (values[i] + values[i + 1]) / 2];
    };
    radialFrames.forEach((f, ti) => {
      const [t0, t1] = edge(times, ti);
      f.temperature_k.forEach((temp, ri) => {
        const [r0, r1] = edge(r, ri);
        // Close the first cell to the 0 axis; the solver domain begins at r_min.
        const x0 = x(ri === 0 ? 0 : Math.max(0, r0));
        const x1 = x(r1);
        const y0 = y(Math.max(0, t0));
        const y1 = y(Math.min(tMax, t1));
        cells
          .append("rect")
          .attr("class", "heat-cell")
          .attr("x", x0)
          .attr("y", Math.min(y0, y1))
          .attr("width", Math.max(x1 - x0 + 0.5, 1))
          .attr("height", Math.max(Math.abs(y1 - y0) + 0.5, 1))
          .attr("fill", color(temp));
      });
    });

    addAxes(svg, {
      W,
      H,
      x,
      y,
      m,
      xTicks: 6,
      yTicks: 5,
      xFormat: d3.format(".0f"),
      yFormat: d3.format(".2f"),
    });

    const barX = W - m.right + 26;
    const barW = 14;
    const barTop = m.top;
    const barH = H - m.top - m.bottom;
    const defs = svg.select("defs");
    const grad = defs
      .append("linearGradient")
      .attr("id", "radial-time-color")
      .attr("x1", "0%")
      .attr("x2", "0%")
      .attr("y1", "100%")
      .attr("y2", "0%");
    d3.range(0, 1.001, 0.1).forEach((p) => {
      const v = color.domain()[0] + p * (color.domain()[1] - color.domain()[0]);
      grad
        .append("stop")
        .attr("offset", `${p * 100}%`)
        .attr("stop-color", color(v));
    });
    svg
      .append("rect")
      .attr("x", barX)
      .attr("y", barTop)
      .attr("width", barW)
      .attr("height", barH)
      .attr("rx", 3)
      .attr("fill", "url(#radial-time-color)");

    const cbar = d3
      .scaleLinear()
      .domain(color.domain())
      .range([barTop + barH, barTop]);
    svg
      .append("g")
      .attr("class", "axis axis-colorbar")
      .attr("transform", `translate(${barX + barW},0)`)
      .call(
        d3
          .axisRight(cbar)
          .ticks(4)
          .tickSize(0)
          .tickPadding(6)
          .tickFormat(autoFormat)
      );
    svg
      .append("text")
      .attr("class", "axis-title")
      .attr("x", barX)
      .attr("y", barTop - 6)
      .text("T (K)");

    addAxisTitles(svg, { W, H, m, x: "radius (mm)", y: "t (s)" });

    svg
      .append("line")
      .attr("class", "chart-boundary")
      .attr("x1", x(r[0]))
      .attr("x2", x(r[0]))
      .attr("y1", m.top)
      .attr("y2", H - m.bottom)
      .append("title")
      .text(`Solver inner boundary r_min = ${r[0].toFixed(2)} mm`);

    const focus = svg.append("g").attr("class", "hover-focus").style("display", "none");
    const focusCell = focus
      .append("rect")
      .attr("fill", "none")
      .attr("stroke", "#ffffff")
      .attr("stroke-width", 1.2);
    svg
      .append("rect")
      .attr("class", "hover-layer")
      .attr("x", m.left)
      .attr("y", m.top)
      .attr("width", Math.max(W - m.left - m.right, 1))
      .attr("height", Math.max(H - m.top - m.bottom, 1))
      .attr("fill", "transparent")
      .on("pointermove", (event) => {
        const [px, py] = d3.pointer(event, svg.node());
        const ri = nearestValueIndex(r, x.invert(px));
        const ti = nearestValueIndex(times, y.invert(py));
        const [r0, r1] = edge(r, ri);
        const [t0, t1] = edge(times, ti);
        const x0 = x(ri === 0 ? 0 : Math.max(0, r0));
        const x1 = x(r1);
        const y0 = y(Math.max(0, t0));
        const y1 = y(Math.min(tMax, t1));
        focus.style("display", null);
        focusCell
          .attr("x", x0)
          .attr("y", Math.min(y0, y1))
          .attr("width", Math.max(x1 - x0, 1))
          .attr("height", Math.max(Math.abs(y1 - y0), 1));
        setHover({
          ...placeTooltip(px, py, W, H),
          title: `x = ${r[ri].toFixed(2)} mm · y = ${times[ti].toFixed(3)} s`,
          rows: [
            {
              label: "T",
              value: `${d3.format(",.1f")(radialFrames[ti].temperature_k[ri])} K`,
              color: "#ff7043",
            },
          ],
        });
      })
      .on("pointerleave", () => {
        focus.style("display", "none");
        setHover(null);
      });
  }, [radialFrames, measured]);

  return (
    <div className="panel mini-graph-panel">
      <div className="panel-head">
        <h2>Temperature Field T(r, t)</h2>
        <span className="muted small">1D radial solver snapshots</span>
      </div>
      <div className="chart-wrap" ref={wrapRef}>
        <svg
          ref={svgRef}
          className="chart-svg"
          data-chart="temperature-field"
          role="img"
          aria-label="Radial temperature field over time"
        />
        <ChartTooltip hover={hover} />
      </div>
      {!radialFrames?.length && (
        <p className="muted small">
          Run a simulation to see the radial time history.
        </p>
      )}
    </div>
  );
}

function Suggestions({ history, finalData }) {
  const items = buildSuggestions(history, finalData);

  return (
    <div className="panel mini-graph-panel suggestions-panel">
      <div className="panel-head">
        <h2>Suggestions</h2>
        <span className="muted small">rule-based, from this run</span>
      </div>
      {items.length ? (
        <ul className="suggestion-list">
          {items.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      ) : (
        <p className="muted small">Run a simulation for analysis suggestions.</p>
      )}
    </div>
  );
}
