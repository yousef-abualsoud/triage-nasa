import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";

/**
 * Chart margins: the bottom/left/right gutters hold tick labels *and* rotated
 * axis titles, so titles never sit inside the data area.
 */
export const CHART_M = { top: 18, right: 74, bottom: 48, left: 68 };

/**
 * Render D3 charts at their real CSS pixel width. The old components drew at a
 * fixed 430px viewBox and scaled the SVG to the panel, which blew up axis text
 * on wide panels. Measuring the wrapper keeps 10–11px labels 10–11px.
 */
export function useChartWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const measure = () => {
      const w = Math.floor(el.getBoundingClientRect().width);
      if (w > 0) setWidth((prev) => (prev === w ? prev : w));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return [ref, width];
}

/** Subtle horizontal + vertical gridlines behind the plotted data. */
export function addGrid(svg, { W, H, x, y, m = CHART_M, xTicks = 5, yTicks = 4 }) {
  const innerW = Math.max(W - m.left - m.right, 1);
  const innerH = Math.max(H - m.top - m.bottom, 1);
  svg
    .append("g")
    .attr("class", "grid")
    .attr("transform", `translate(${m.left},0)`)
    .call(d3.axisLeft(y).ticks(yTicks).tickSize(-innerW).tickFormat(""));
  svg
    .append("g")
    .attr("class", "grid grid-x")
    .attr("transform", `translate(0,${H - m.bottom})`)
    .call(d3.axisBottom(x).ticks(xTicks).tickSize(-innerH).tickFormat(""));
}

/** Bottom + left axes with consistent tick padding and optional formatters. */
export function addAxes(svg, { W, H, x, y, m = CHART_M, xTicks = 5, yTicks = 4, xFormat, yFormat }) {
  svg
    .append("g")
    .attr("class", "axis axis-x")
    .attr("transform", `translate(0,${H - m.bottom})`)
    .call(d3.axisBottom(x).ticks(xTicks).tickPadding(7).tickFormat(xFormat));
  svg
    .append("g")
    .attr("class", "axis axis-y")
    .attr("transform", `translate(${m.left},0)`)
    .call(d3.axisLeft(y).ticks(yTicks).tickPadding(7).tickFormat(yFormat));
}

/** Rotated y titles live in the left/right gutters; x title under the ticks. */
export function addAxisTitles(svg, { W, H, m = CHART_M, x, y, yRight }) {
  const cy = (m.top + H - m.bottom) / 2;
  if (x) {
    svg
      .append("text")
      .attr("class", "axis-title")
      .attr("x", (m.left + W - m.right) / 2)
      .attr("y", H - 9)
      .attr("text-anchor", "middle")
      .text(x);
  }
  if (y) {
    svg
      .append("text")
      .attr("class", "axis-title")
      .attr("transform", `translate(12,${cy}) rotate(-90)`)
      .attr("text-anchor", "middle")
      .text(y);
  }
  if (yRight) {
    svg
      .append("text")
      .attr("class", "axis-title")
      .attr("transform", `translate(${W - 10},${cy}) rotate(90)`)
      .attr("text-anchor", "middle")
      .text(yRight);
  }
}

/** Readable tick labels for quantities that span several orders of magnitude. */
export function autoFormat(value) {
  const a = Math.abs(value);
  if (value === 0) return "0";
  if (a >= 1000) return d3.format(",.0f")(value);
  if (a >= 10) return d3.format(".0f")(value);
  if (a >= 1) return d3.format(".2f")(value);
  if (a >= 0.01) return d3.format(".3f")(value);
  return d3.format(".1e")(value);
}

/** Index of the sampled value closest to a cursor position. */
export function nearestValueIndex(values, target) {
  if (!values?.length) return 0;
  const bisect = d3.bisector((value) => value).center;
  return Math.max(0, Math.min(values.length - 1, bisect(values, target)));
}

/** Place an HTML tooltip near the cursor, flipping at the right edge. */
export function placeTooltip(px, py, W, H, width = 205) {
  const flip = px > W - width - 14;
  return {
    left: flip ? px - 12 : px + 12,
    top: Math.max(6, Math.min(py + 14, H - 86)),
    flip,
  };
}
