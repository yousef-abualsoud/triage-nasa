/**
 * Rasterise the off-screen report charts to PNG for jsPDF.
 *
 * The dashboard SVGs style themselves through stylesheet classes, so a raw
 * XMLSerializer dump would lose every fill/stroke. We copy the computed styles
 * onto the clone before serialising, which keeps axes, labels, gridlines, and
 * series colours identical to what the user sees.
 */
const STYLE_PROPS = [
  "color",
  "display",
  "visibility",
  "opacity",
  "fill",
  "fill-opacity",
  "stroke",
  "stroke-width",
  "stroke-opacity",
  "stroke-dasharray",
  "stroke-linecap",
  "stroke-linejoin",
  "shape-rendering",
  "font-family",
  "font-size",
  "font-weight",
  "letter-spacing",
  "text-anchor",
  "dominant-baseline",
];

const CHART_KEYS = [
  "burn-curves",
  "solver-radial",
  "species",
  "radial-temperature",
  "temperature-field",
  "history-soot",
  "history-burned",
  "iteration-delta-t",
];

export function expectedReportChartKeys({
  history,
  frame,
  finalRadial,
  radialFrames,
} = {}) {
  return CHART_KEYS.filter((key) => {
    if (
      key.startsWith("history-") ||
      key === "burn-curves" ||
      key === "iteration-delta-t"
    ) {
      return Boolean(history?.length);
    }
    if (key === "solver-radial") return Boolean(finalRadial?.r_m?.length);
    if (key === "species") {
      return Boolean(
        finalRadial?.mass_fractions &&
          Object.keys(finalRadial.mass_fractions).length
      );
    }
    if (key === "radial-temperature") return Boolean(frame?.length);
    if (key === "temperature-field") return Boolean(radialFrames?.length);
    return false;
  });
}

function svgIsReady(svg) {
  const vb = svg.viewBox?.baseVal;
  if (!vb || !vb.width) return false;
  const wrap = svg.parentElement;
  const wrapW = wrap?.getBoundingClientRect().width ?? 0;
  if (wrapW > 0 && Math.abs(vb.width - wrapW) > 2) return false;
  return svg.querySelectorAll("path, rect, line").length > 2;
}

/**
 * Wait until every expected chart has rendered at its measured container
 * width. useChartWidth measures after mount and triggers a second D3 pass, so
 * checking only for SVG presence would sometimes capture the default width.
 */
export function waitForReportCharts(
  host,
  expectedKeys = CHART_KEYS,
  timeoutMs = 8000
) {
  return new Promise((resolve, reject) => {
    const started = performance.now();
    const tick = () => {
      if (!host) {
        reject(new Error("report renderer is not mounted"));
        return;
      }
      if (!expectedKeys.length) {
        resolve([]);
        return;
      }
      const svgs = [...host.querySelectorAll("svg[data-chart]")];
      const found = new Set(svgs.map((s) => s.dataset.chart));
      if (
        expectedKeys.every((key) => found.has(key)) &&
        svgs
          .filter((svg) => expectedKeys.includes(svg.dataset.chart))
          .every(svgIsReady)
      ) {
        resolve(svgs);
        return;
      }
      if (performance.now() - started > timeoutMs) {
        reject(new Error("charts did not finish rendering"));
        return;
      }
      window.setTimeout(tick, 80);
    };
    requestAnimationFrame(() => requestAnimationFrame(tick));
  });
}

function inlineComputedStyles(source, clone) {
  const srcEls = [source, ...source.querySelectorAll("*")];
  const dstEls = [clone, ...clone.querySelectorAll("*")];
  const count = Math.min(srcEls.length, dstEls.length);
  for (let i = 0; i < count; i++) {
    const cs = window.getComputedStyle(srcEls[i]);
    const target = dstEls[i];
    for (const prop of STYLE_PROPS) {
      const value = cs.getPropertyValue(prop);
      if (value) target.style.setProperty(prop, value);
    }
  }
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("chart rasterisation failed"));
    img.src = url;
  });
}

async function captureSvg(svg) {
  const vb = svg.viewBox.baseVal;
  const width = Math.max(vb.width || svg.getBoundingClientRect().width, 1);
  const height = Math.max(vb.height || svg.getBoundingClientRect().height, 1);

  const clone = svg.cloneNode(true);
  inlineComputedStyles(svg, clone);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  clone.setAttribute("viewBox", `0 0 ${width} ${height}`);
  clone.style.width = `${width}px`;
  clone.style.height = `${height}px`;
  clone.style.overflow = "visible";

  const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  bg.setAttribute("x", "0");
  bg.setAttribute("y", "0");
  bg.setAttribute("width", String(width));
  bg.setAttribute("height", String(height));
  bg.setAttribute("fill", "#141824");
  clone.insertBefore(bg, clone.firstChild);

  const xml = new XMLSerializer().serializeToString(clone);
  const blob = new Blob([xml], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const img = await loadImage(url);
    const scale = Math.min(2.5, 3200 / width);
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#141824";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return {
      dataUrl: canvas.toDataURL("image/png"),
      width,
      height,
    };
  } finally {
    URL.revokeObjectURL(url);
  }
}

export async function captureReportCharts(host, expectedKeys) {
  const svgs = await waitForReportCharts(host, expectedKeys);
  const out = {};
  for (const svg of svgs) {
    const key = svg.dataset.chart;
    if (!key || !expectedKeys.includes(key) || out[key]) continue;
    out[key] = await captureSvg(svg);
  }
  return out;
}
