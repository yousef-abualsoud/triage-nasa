import { jsPDF } from "jspdf";
import { buildSuggestions } from "./diagnostics.js";

const PAGE_W = 210;
const PAGE_H = 297;
const M = 16;
const CW = PAGE_W - M * 2;
const BOTTOM = 279;

const C = {
  bg: [11, 13, 20], // --bg
  panel: [20, 24, 36], // --panel
  panel2: [27, 32, 48], // --panel-2
  ink: [232, 234, 242], // --text
  muted: [139, 147, 171], // --muted
  faint: [110, 120, 144],
  accent: [255, 112, 67], // --accent
  accentSoft: [48, 31, 27],
  navy: [24, 30, 46],
  line: [42, 50, 71], // --border
  ok: [102, 187, 106], // --ok
  warn: [255, 158, 64],
};

const CHART_CAPTIONS = [
  [
    "burn-curves",
    "Burn curves: simulation vs NASA PSI",
    "Simulated peak temperature (left axis) and flame radius (right axis) over time. Dashed markers are NASA PSI telemetry when a comparable profile exists.",
  ],
  [
    "solver-radial",
    "Solver radial fields",
    "Final-step radial temperature and volumetric heat release. The dashed vertical marker is the solver inner boundary r_min; values left of it are held constant for display.",
  ],
  [
    "species",
    "Species profiles",
    "Fuel and oxidizer mass fractions across the radial domain at the final solver step.",
  ],
  [
    "radial-temperature",
    "Radial temperature profile",
    "Angle-averaged temperature profile of the currently selected 2D frame.",
  ],
  [
    "temperature-field",
    "Temperature field T(r, t)",
    "Radial temperature snapshots over the run, from the t = 0 initial state to run end.",
  ],
  [
    "history-soot",
    "Soot and mean temperature",
    "Soot index (left axis) and mean temperature (right axis) across solver iterations.",
  ],
  [
    "history-burned",
    "Fuel burned fraction",
    "Fraction of the initial fuel mass consumed across solver iterations.",
  ],
  [
    "iteration-delta-t",
    "Iteration graph",
    "Peak-temperature change between saved iterations: ΔT = T2 - T1, with T1 = 0 K on the first point.",
  ],
];

/**
 * Standard PDF fonts use WinAnsi, not full Unicode. Map the symbols used by
 * the solver/report copy so the exported text never turns into tofu.
 */
const UNICODE_MAP = [
  [/[\u2018\u2019]/g, "'"],
  [/[\u201c\u201d]/g, '"'],
  [/[\u2013\u2014]/g, "-"],
  [/\u2022/g, "-"],
  [/\u00b5|\u03bc/g, "u"],
  [/\u00b0/g, " deg"],
  [/\u00b1/g, "+/-"],
  [/\u00b2/g, "2"],
  [/\u00b3/g, "3"],
  [/\u00b7/g, "-"],
  [/\u0394/g, "Delta "],
  [/\u03b1/g, "alpha"],
  [/\u03b2/g, "beta"],
  [/\u03b3/g, "gamma"],
  [/\u03b4/g, "delta"],
  [/\u03bb/g, "lambda"],
  [/\u03c1/g, "rho"],
  [/\u03c3/g, "sigma"],
  [/\u03c4/g, "tau"],
  [/\u03b8/g, "theta"],
  [/\u03c6/g, "phi"],
  [/\u03a9/g, "ohm"],
  [/\u2264/g, "<="],
  [/\u2265/g, ">="],
  [/\u2248/g, "~"],
  [/\u2260/g, "!="],
  [/\u2192/g, "->"],
  [/\u2190/g, "<-"],
  [/\u00d7/g, "x"],
  [/\u221e/g, "inf"],
  [/\u221a/g, "sqrt"],
  [/\u222b/g, "integral"],
  [/\u2202/g, "d"],
  [/\u2090/g, "a"],
  [/\u2091/g, "e"],
  [/\u2092/g, "o"],
  [/\u2093/g, "x"],
  [/\u1d63/g, "r"],
  [/\u1e41/g, "m"],
  [/\u0307/g, ""],
  [/\u2080/g, "0"],
  [/\u2081/g, "1"],
  [/\u2082/g, "2"],
  [/\u2083/g, "3"],
  [/\u2084/g, "4"],
  [/\u2085/g, "5"],
  [/\u2086/g, "6"],
  [/\u2087/g, "7"],
  [/\u2088/g, "8"],
  [/\u2089/g, "9"],
  [/\u2070/g, "0"],
  [/\u00b9/g, "1"],
  [/\u2074/g, "4"],
  [/\u2075/g, "5"],
  [/\u2076/g, "6"],
  [/\u2077/g, "7"],
  [/\u2078/g, "8"],
  [/\u2079/g, "9"],
  [/\u207b/g, "-"],
  [/\u207a/g, "+"],
];

function ascii(value) {
  let text = String(value ?? "");
  for (const [pattern, replacement] of UNICODE_MAP) {
    text = text.replace(pattern, replacement);
  }
  return text.replace(/[^\x20-\x7e\n\r\t]/g, "?");
}

function num(value, digits = 1) {
  if (value == null || !Number.isFinite(Number(value))) return "n/a";
  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function pct(value, digits = 0) {
  if (value == null || !Number.isFinite(Number(value))) return "n/a";
  return `${num(Number(value) * 100, digits)}%`;
}

function sci(value, digits = 2) {
  if (value == null || !Number.isFinite(Number(value))) return "n/a";
  const n = Number(value);
  if (n === 0) return "0";
  if (Math.abs(n) >= 0.001 && Math.abs(n) < 10000) return num(n, digits);
  return n.toExponential(digits);
}

function bool(value) {
  if (value == null) return "n/a";
  return value ? "Yes" : "No";
}

function formatDate(date) {
  return `${date.toISOString().replace("T", " ").slice(0, 19)} UTC`;
}

function setFont(doc, size, style = "normal", color = C.ink) {
  doc.setFont("helvetica", style);
  doc.setFontSize(size);
  doc.setTextColor(color[0], color[1], color[2]);
}

/** Dark A4 page matching the dashboard's --bg / --accent scheme. */
function paintPage(doc) {
  doc.setFillColor(C.bg[0], C.bg[1], C.bg[2]);
  doc.rect(0, 0, PAGE_W, PAGE_H, "F");
  doc.setFillColor(C.accent[0], C.accent[1], C.accent[2]);
  doc.rect(0, 0, PAGE_W, 1.6, "F");
}

function drawRunningHeader(st) {
  const { doc } = st;
  setFont(doc, 8, "bold", C.faint);
  const label = "T.R.I.A.G.E.";
  const charSpace = 1.4;
  const width =
    doc.getTextWidth(label) + charSpace * (label.length - 1);
  doc.setCharSpace(charSpace);
  doc.text(label, (PAGE_W - width) / 2, 12);
  doc.setCharSpace(0);
  doc.setDrawColor(C.line[0], C.line[1], C.line[2]);
  doc.setLineWidth(0.2);
  doc.line(M, 15.5, PAGE_W - M, 15.5);
  st.y = 23;
}

function ensure(st, height) {
  if (st.y + height <= BOTTOM) return;
  st.doc.addPage();
  paintPage(st.doc);
  drawRunningHeader(st);
}

function heading(st, text) {
  const { doc } = st;
  ensure(st, 15);
  st.y += 3;
  doc.setFillColor(C.accent[0], C.accent[1], C.accent[2]);
  doc.rect(M, st.y - 3.4, 1.9, 5.2, "F");
  setFont(doc, 12.2, "bold", C.ink);
  doc.text(ascii(text), M + 5.2, st.y + 0.8);
  st.y += 5.8;
  doc.setDrawColor(C.line[0], C.line[1], C.line[2]);
  doc.setLineWidth(0.25);
  doc.line(M, st.y, PAGE_W - M, st.y);
  st.y += 4.8;
}

function subheading(st, text, { size = 9.6, gap = 2.2 } = {}) {
  ensure(st, 8);
  setFont(st.doc, size, "bold", C.ink);
  st.doc.text(ascii(text), M, st.y + 2.4);
  st.y += 4.6 + gap;
}

function paragraph(st, text, opts = {}) {
  const size = opts.size ?? 8.6;
  const leading = opts.leading ?? 4.15;
  const width = opts.width ?? CW;
  const x = opts.x ?? M;
  const gap = opts.gap ?? 2.6;
  const doc = st.doc;
  setFont(doc, size, opts.style ?? "normal", opts.color ?? C.ink);
  const lines = doc.splitTextToSize(ascii(text), width);
  lines.forEach((line) => {
    ensure(st, leading);
    setFont(doc, size, opts.style ?? "normal", opts.color ?? C.ink);
    doc.text(line, x, st.y);
    st.y += leading;
  });
  st.y += gap;
}

function bullet(st, text, opts = {}) {
  const doc = st.doc;
  const size = opts.size ?? 8.5;
  const leading = opts.leading ?? 4.05;
  setFont(doc, size, "normal", opts.color ?? C.ink);
  const lines = doc.splitTextToSize(ascii(text), CW - 7);
  ensure(st, lines.length * leading + 2);
  doc.setFillColor(C.accent[0], C.accent[1], C.accent[2]);
  doc.circle(M + 1.7, st.y - 1.1, 0.75, "F");
  lines.forEach((line) => {
    ensure(st, leading);
    setFont(doc, size, "normal", opts.color ?? C.ink);
    doc.text(line, M + 5.4, st.y);
    st.y += leading;
  });
  st.y += opts.gap ?? 1.5;
}

function numericList(st, marker, text) {
  const doc = st.doc;
  const size = 8.5;
  const leading = 4.05;
  setFont(doc, size, "bold", C.accent);
  const lines = doc.splitTextToSize(ascii(text), CW - 9);
  ensure(st, lines.length * leading + 2);
  doc.text(ascii(marker), M + 1, st.y);
  lines.forEach((line) => {
    ensure(st, leading);
    setFont(doc, size, "normal", C.ink);
    doc.text(line, M + 7, st.y);
    st.y += leading;
  });
  st.y += 1.5;
}

function metricCards(st, items) {
  const doc = st.doc;
  const gap = 3;
  const cardW = (CW - gap * (items.length - 1)) / items.length;
  const cardH = 17;
  ensure(st, cardH + 5);
  items.forEach((item, index) => {
    const x = M + index * (cardW + gap);
    doc.setFillColor(C.panel[0], C.panel[1], C.panel[2]);
    doc.roundedRect(x, st.y, cardW, cardH, 1.4, 1.4, "F");
    doc.setDrawColor(C.line[0], C.line[1], C.line[2]);
    doc.setLineWidth(0.2);
    doc.roundedRect(x, st.y, cardW, cardH, 1.4, 1.4, "S");
    setFont(doc, 6.4, "bold", C.muted);
    doc.text(ascii(item.label.toUpperCase()), x + 3, st.y + 5.3);
    setFont(doc, item.size ?? 12.5, "bold", item.color ?? C.ink);
    doc.text(ascii(item.value), x + 3, st.y + 12.4);
  });
  st.y += cardH + 5;
}

function keyValueGrid(st, pairs, { columns = 2, rowGap = 1.1 } = {}) {
  const doc = st.doc;
  const colGap = 5;
  const colW = (CW - colGap * (columns - 1)) / columns;
  // Long labels such as AMBIENT TEMPERATURE must not run into their values.
  setFont(doc, 6.3, "bold", C.muted);
  const longestLabel = Math.max(
    0,
    ...pairs.map((pair) =>
      doc.getTextWidth(ascii(String(pair[0]).toUpperCase()))
    )
  );
  const labelW = Math.min(colW * 0.52, Math.max(29, longestLabel + 3));
  const valueW = colW - labelW;
  const rows = Math.ceil(pairs.length / columns);

  for (let row = 0; row < rows; row++) {
    let rowH = 5.2;
    const cells = [];
    for (let col = 0; col < columns; col++) {
      const pair = pairs[row * columns + col];
      if (!pair) continue;
      setFont(doc, 7.6, "normal", C.ink);
      const lines = doc.splitTextToSize(ascii(pair[1] ?? "n/a"), valueW);
      cells.push({ pair, lines });
      rowH = Math.max(rowH, lines.length * 3.3 + 2.2);
    }
    ensure(st, rowH + rowGap);
    const rowY = st.y;
    cells.forEach(({ pair, lines }, col) => {
      const x = M + col * (colW + colGap);
      if (row % 2 === 0) {
        doc.setFillColor(C.panel[0], C.panel[1], C.panel[2]);
        doc.rect(x, rowY, colW, rowH, "F");
      }
      setFont(doc, 6.3, "bold", C.muted);
      doc.text(ascii(String(pair[0]).toUpperCase()), x + 1.5, rowY + 3.6);
      setFont(doc, 7.6, "normal", C.ink);
      lines.forEach((line, i) => {
        doc.text(line, x + labelW, rowY + 3.6 + i * 3.3);
      });
    });
    doc.setDrawColor(C.line[0], C.line[1], C.line[2]);
    doc.setLineWidth(0.15);
    doc.line(M, rowY + rowH, PAGE_W - M, rowY + rowH);
    st.y = rowY + rowH + rowGap;
  }
}

function drawTableHeader(st, columns) {
  const doc = st.doc;
  const headerH = 6.8;
  doc.setFillColor(C.panel2[0], C.panel2[1], C.panel2[2]);
  doc.rect(M, st.y, CW, headerH, "F");
  let x = M;
  columns.forEach((col) => {
    setFont(doc, 6.8, "bold", C.ink);
    const align = col.align ?? "left";
    const tx =
      align === "right"
        ? x + col.width - 1.8
        : align === "center"
          ? x + col.width / 2
          : x + 1.8;
    doc.text(ascii(col.label.toUpperCase()), tx, st.y + 4.4, { align });
    x += col.width;
  });
  st.y += headerH;
}

function table(st, columns, rows) {
  const doc = st.doc;
  const total = columns.reduce((sum, col) => sum + col.width, 0);
  const scaled = columns.map((col) => ({ ...col, width: (col.width / total) * CW }));
  const padding = 1.8;
  const leading = 3.25;

  const rowHeight = (row) => {
    let lines = 1;
    scaled.forEach((col, index) => {
      setFont(doc, 7.3, "normal", C.ink);
      const cellLines = doc.splitTextToSize(
        ascii(row[index] ?? "n/a"),
        Math.max(col.width - padding * 2, 8)
      );
      lines = Math.max(lines, cellLines.length);
    });
    return Math.max(6.4, lines * leading + padding * 2);
  };

  ensure(st, 7 + rowHeight(rows[0] ?? []));
  drawTableHeader(st, scaled);

  rows.forEach((row, rowIndex) => {
    const height = rowHeight(row);
    if (st.y + height > BOTTOM) {
      doc.addPage();
      paintPage(doc);
      drawRunningHeader(st);
      drawTableHeader(st, scaled);
    }
    const y = st.y;
    doc.setFillColor(
      ...(rowIndex % 2 === 0 ? C.panel : C.bg)
    );
    doc.rect(M, y, CW, height, "F");
    let x = M;
    row.forEach((cell, index) => {
      const col = scaled[index];
      setFont(doc, 7.3, "normal", C.ink);
      const lines = doc.splitTextToSize(
        ascii(cell ?? "n/a"),
        Math.max(col.width - padding * 2, 8)
      );
      lines.forEach((line, lineIndex) => {
        const align = col.align ?? "left";
        const tx =
          align === "right"
            ? x + col.width - padding
            : align === "center"
              ? x + col.width / 2
              : x + padding;
        doc.text(line, tx, y + padding + 2.4 + lineIndex * leading, {
          align,
        });
      });
      x += col.width;
    });
    doc.setDrawColor(C.line[0], C.line[1], C.line[2]);
    doc.setLineWidth(0.15);
    doc.line(M, y + height, PAGE_W - M, y + height);
    st.y = y + height;
  });
  st.y += 4;
}

function chartFigure(st, figureNumber, chart, title, caption) {
  if (!chart?.dataUrl) return;
  const doc = st.doc;
  const imgH = (CW * chart.height) / chart.width;
  const titleH = 5.2;
  setFont(doc, 7.2, "normal", C.muted);
  const capLines = doc.splitTextToSize(ascii(caption), CW);
  const capH = capLines.length * 3.15;
  ensure(st, titleH + imgH + 4.4 + capH + 8);

  setFont(doc, 8.6, "bold", C.ink);
  doc.text(
    ascii(`Figure ${figureNumber}. ${title}`),
    M,
    st.y + 2.6
  );
  st.y += titleH;

  doc.addImage(chart.dataUrl, "PNG", M, st.y, CW, imgH, undefined, "FAST");
  doc.setDrawColor(C.line[0], C.line[1], C.line[2]);
  doc.setLineWidth(0.2);
  doc.rect(M, st.y, CW, imgH, "S");
  // One blank line of breathing room between the plot edge and its caption.
  st.y += imgH + 4.4;

  setFont(doc, 7.2, "normal", C.muted);
  capLines.forEach((line) => {
    doc.text(line, M, st.y);
    st.y += 3.15;
  });
  // One blank line between figures so adjacent charts never read as one block.
  st.y += 8.4;
}

function markdownReport(st, markdown) {
  const lines = String(markdown ?? "").split(/\r?\n/);
  let paragraphLines = [];
  const flush = () => {
    if (!paragraphLines.length) return;
    paragraph(st, paragraphLines.join(" "), { size: 8.6, gap: 2.1 });
    paragraphLines = [];
  };

  lines.forEach((raw) => {
    const line = raw.trimEnd();
    const trimmed = line.trim();
    if (!trimmed) {
      flush();
      st.y += 1.1;
      return;
    }
    const headingMatch = trimmed.match(/^(#{1,4})\s+(.*)$/);
    if (headingMatch) {
      flush();
      const level = headingMatch[1].length;
      subheading(st, headingMatch[2].replace(/\*\*/g, ""), {
        size: level <= 2 ? 10.2 : 9.1,
        gap: level <= 2 ? 2.4 : 1.6,
      });
      return;
    }
    const bulletMatch = trimmed.match(/^[-*]\s+(.*)$/);
    if (bulletMatch) {
      flush();
      bullet(st, cleanInline(bulletMatch[1]));
      return;
    }
    const numberMatch = trimmed.match(/^(\d+[.)])\s+(.*)$/);
    if (numberMatch) {
      flush();
      numericList(st, numberMatch[1], cleanInline(numberMatch[2]));
      return;
    }
    if (trimmed.startsWith(">")) {
      flush();
      paragraph(st, cleanInline(trimmed.replace(/^>\s?/, "")), {
        style: "italic",
        color: C.muted,
        size: 8.2,
        width: CW - 5,
        x: M + 5,
        gap: 2.1,
      });
      return;
    }
    paragraphLines.push(cleanInline(trimmed));
  });
  flush();
}

function cleanInline(text) {
  return String(text ?? "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
}

function safetyFlagColor(value, warnWhenTrue = true) {
  if (value == null) return C.muted;
  return value === warnWhenTrue ? C.warn : C.ok;
}

function chartLookup(charts) {
  const map = new Map();
  (charts ?? []).forEach((entry) => {
    if (entry?.key) map.set(entry.key, entry);
  });
  return map;
}

/**
 * Build the full A4 PDF and return the jsPDF document (caller decides whether
 * to save it, which keeps the generator testable).
 */
export function generateRunReport({
  simResult,
  verdictMsg,
  tier2Report,
  charts = [],
  generatedAt = new Date(),
}) {
  const doc = new jsPDF({
    orientation: "portrait",
    unit: "mm",
    format: "a4",
    compress: true,
  });
  doc.setProperties({
    title: `T.R.I.A.G.E. simulation report - ${simResult?.run_id ?? "run"}`,
    subject: "1D spherical microgravity combustion run with NASA PSI comparison",
    author: "T.R.I.A.G.E.",
    creator: "T.R.I.A.G.E. dashboard",
    keywords: "NASA, microgravity, combustion, PSI, fire safety, TRIAGE",
  });

  const st = { doc, y: M };
  const cfg = simResult?.config ?? {};
  const final = simResult?.final ?? {};
  const unified = simResult?.unified ?? {};
  const history = simResult?.history ?? [];
  const last = history.length ? history[history.length - 1] : {};
  const verdict = verdictMsg?.verdict ?? null;
  const gt = verdictMsg?.ground_truth ?? null;
  const match = verdictMsg?.match ?? null;
  const chartByKey = chartLookup(charts);
  const runId = simResult?.run_id ?? "unknown";
  const generated = formatDate(generatedAt);
  const dateStamp = generatedAt.toISOString().slice(0, 10);

  const peakTemp = final.peak_temp_k ?? last.peak_temp_k;
  const radiusM = final.max_flame_radius_m ?? last.max_flame_radius_m;
  const burned = last.fuel_burned_fraction;
  const burnDuration =
    unified.burn_duration_s ?? final?.diagnostics?.run_end_time_s;

  // ---- Cover / title block -------------------------------------------------
  paintPage(doc);
  doc.setFillColor(C.accent[0], C.accent[1], C.accent[2]);
  doc.rect(0, 0, PAGE_W, 2.2, "F");
  setFont(doc, 28, "bold", C.ink);
  const wordmark = "T.R.I.A.G.E.";
  const wordmarkSpace = 2.2;
  const wordmarkWidth =
    doc.getTextWidth(wordmark) + wordmarkSpace * (wordmark.length - 1);
  doc.setCharSpace(wordmarkSpace);
  doc.text(wordmark, (PAGE_W - wordmarkWidth) / 2, 27.5);
  doc.setCharSpace(0);
  setFont(doc, 8.4, "normal", C.muted);
  doc.text(
    "Thermal Reaction Inference & Anomaly Grading Engine",
    PAGE_W / 2,
    34.8,
    { align: "center" }
  );
  setFont(doc, 10.8, "bold", C.accent);
  doc.text("SIMULATION RUN REPORT", PAGE_W / 2, 43.2, { align: "center" });
  setFont(doc, 7.5, "normal", C.muted);
  doc.text(`Run ${ascii(runId)}  |  ${ascii(generated)}`, PAGE_W / 2, 49, {
    align: "center",
  });
  doc.setDrawColor(C.accent[0], C.accent[1], C.accent[2]);
  doc.setLineWidth(0.45);
  doc.line(PAGE_W / 2 - 22, 53.4, PAGE_W / 2 + 22, 53.4);
  st.y = 61;

  metricCards(st, [
    {
      label: "Peak temperature",
      value: peakTemp != null ? `${num(peakTemp, 0)} K` : "n/a",
    },
    {
      label: "Flame radius",
      value: radiusM != null ? `${num(radiusM * 1000, 1)} mm` : "n/a",
    },
    {
      label: "Fuel burned",
      value: burned != null ? pct(burned) : "n/a",
    },
    {
      label: "Burn duration",
      value: burnDuration != null ? `${num(burnDuration, 3)} s` : "n/a",
    },
  ]);

  paragraph(
    st,
    "This report consolidates the simulation run, its tier-1 NASA PSI comparison, all diagnostic charts, and the tier-2 fire-safety synthesis generated for this run.",
    { size: 8.4, color: C.muted, gap: 1.8 }
  );

  heading(st, "Run configuration");
  keyValueGrid(st, [
    ["Fuel", cfg.fuel],
    ["Oxidizer", cfg.oxidizer],
    ["Oxygen", `${num(cfg.oxygen_pct, 1)} %`],
    ["Ambient pressure", `${num(cfg.ambient_pressure_bar, 2)} bar`],
    ["Ambient temperature", `${num(cfg.ambient_temperature_k, 0)} K`],
    ["Gravity mode", cfg.gravity_mode],
    ["Mixing mode", cfg.mixing_mode],
    ["Equivalence ratio", num(cfg.equivalence_ratio, 2)],
    ["Mass flow", `${sci(cfg.mass_flow_kg_s, 2)} kg/s`],
    ["Inlet velocity", `${num(cfg.inlet_velocity_ms, 2)} m/s`],
    ["Ignition", `${cfg.ignition_method ?? "n/a"} (${num(cfg.ignition_energy_j, 2)} J)`],
    ["Geometry", cfg.geometry ?? "spherical_1d"],
    [
      "Radial domain",
      `${num((cfg.r_min_m ?? 0) * 1000, 2)} - ${num((cfg.r_max_m ?? 0) * 1000, 2)} mm`,
    ],
    ["Radial cells", cfg.Nr],
    ["Display grid", `${cfg.nx ?? "n/a"} x ${cfg.ny ?? "n/a"}`],
    ["Time step", `${sci(cfg.dt_s, 4)} s`],
    [
      "Iterations",
      `${cfg.iteration_count ?? "n/a"} (run end ${num(
        final?.diagnostics?.run_end_time_s,
        4
      )} s)`,
    ],
    ["Output interval", `${cfg.output_interval_steps ?? "n/a"} steps`],
    ["Boundaries", `${cfg.inner_bc ?? "n/a"} / ${cfg.outer_bc ?? "n/a"}`],
    ["Experiment ID", cfg.experiment_id || "n/a"],
  ]);

  heading(st, "Simulation outcome");
  keyValueGrid(st, [
    ["Peak temperature", `${num(peakTemp, 1)} K`],
    ["Final flame radius", radiusM != null ? `${num(radiusM * 1000, 1)} mm` : "n/a"],
    ["Fuel burned", burned != null ? pct(burned, 1) : "n/a"],
    ["Mean temperature", `${num(last.mean_temp_k, 1)} K`],
    ["Soot index", num(last.soot_index, 3)],
    ["Soot volume fraction", sci(final.soot_volume_fraction, 3)],
    ["Stability score", `${num(final.stability, 1)} / 100`],
    ["Quenched", final.quenched == null ? "n/a" : bool(final.quenched)],
    ["Quench time", final.quench_time_s == null ? "n/a" : `${num(final.quench_time_s, 4)} s`],
    ["Final flame speed", `${sci(last.flame_speed_m_per_s, 3)} m/s`],
    ["Buoyancy KE", sci(last.buoyancy_ke, 3)],
    ["Solver", simResult?.solver ?? "n/a"],
  ]);

  // ---- Tier 1 verdict and Jev comparison ----------------------------------
  heading(st, "Tier 1 verdict and Jev experiment comparison");

  if (verdict) {
    const engineLabel =
      verdict.engine === "local"
        ? "Deterministic local heuristic (no frontier or Jev call)"
        : `Jev ${verdict.engine_model || "typesafe/jev"} via NanoGPT (US-hosted)`;
    paragraph(st, `Verdict engine: ${engineLabel}.`, {
      size: 8.1,
      color: C.muted,
      gap: 1.8,
    });
    table(
      st,
      [
        { label: "Field", width: 66 },
        { label: "Verdict", width: 82 },
      ],
      [
        ["Flame morphology", String(verdict.flame_morphology ?? "n/a")],
        ["NASA experiment profile match", String(verdict.nasa_experiment_profile_match ?? "n/a")],
        ["Buoyancy-driven convection", bool(verdict.buoyancy_driven_convection)],
        ["Radiant heat loss critical", bool(verdict.radiant_heat_loss_critical)],
        ["Soot volume fraction score", `${num(verdict.soot_volume_fraction_score, 1)} / 100`],
        ["Stability score", `${num(verdict.stability_score, 1)} / 100`],
        ["Delta score", `${num(verdict.delta_score, 1)} / 100`],
        ["Confidence", num(verdict.confidence_score, 2)],
      ]
    );
    if (verdict.notes) {
      paragraph(st, `Verdict notes: ${verdict.notes}`, {
        size: 8.1,
        color: C.muted,
        gap: 2.4,
      });
    }
  } else {
    paragraph(st, "No tier-1 verdict is attached to this run.", {
      color: C.muted,
    });
  }

  if (gt) {
    const identity =
      gt.test_point || gt.experiment_id || gt.accession || "Unidentified test point";
    subheading(st, "Nearest NASA PSI ground truth");
    keyValueGrid(st, [
      ["Test point", identity],
      ["Investigation", gt.investigation || "n/a"],
      ["Accession", gt.accession || "n/a"],
      ["Facility", gt.facility || "n/a"],
      ["Fuel blend", gt.fuel_blend || cfg.fuel || "n/a"],
      ["Atmosphere", gt.atmosphere || "n/a"],
      ["Extinction", gt.extinction == null ? "n/a" : bool(gt.extinction)],
      ["Peak PMT", gt.peak_pmt_ua == null ? "n/a" : `${num(gt.peak_pmt_ua, 2)} uA`],
      [
        "Peak ion current",
        gt.peak_ion_current_ua == null
          ? "n/a"
          : `${num(gt.peak_ion_current_ua, 2)} uA`,
      ],
      ["Source", gt.source || "n/a"],
    ]);

    const agreement = (a, b, scale) => {
      if (a == null || b == null) return null;
      return Math.max(0, 100 - (Math.abs(a - b) / scale) * 100);
    };
    const rows = [
      [
        "Peak temperature",
        `${num(unified.peak_temp_k ?? peakTemp, 0)} K`,
        `${num(gt.peak_temp_k, 0)} K`,
        agreement(unified.peak_temp_k ?? peakTemp, gt.peak_temp_k, 2500) == null
          ? "n/a"
          : `${num(agreement(unified.peak_temp_k ?? peakTemp, gt.peak_temp_k, 2500), 0)}%`,
      ],
      [
        "Flame radius",
        `${num(unified.max_radius_mm, 1)} mm`,
        `${num(gt.max_radius_mm, 1)} mm`,
        agreement(unified.max_radius_mm, gt.max_radius_mm, 40) == null
          ? "n/a"
          : `${num(agreement(unified.max_radius_mm, gt.max_radius_mm, 40), 0)}%`,
      ],
      [
        "Oxygen",
        `${num(unified.oxygen_pct, 1)} %`,
        `${num(gt.oxygen_pct, 1)} %`,
        agreement(unified.oxygen_pct, gt.oxygen_pct, 40) == null
          ? "n/a"
          : `${num(agreement(unified.oxygen_pct, gt.oxygen_pct, 40), 0)}%`,
      ],
      [
        "Pressure",
        `${num(unified.ambient_pressure_bar, 2)} bar`,
        `${num(gt.ambient_pressure_bar, 2)} bar`,
        agreement(unified.ambient_pressure_bar, gt.ambient_pressure_bar, 3) == null
          ? "n/a"
          : `${num(agreement(unified.ambient_pressure_bar, gt.ambient_pressure_bar, 3), 0)}%`,
      ],
    ];
    if (unified.burn_duration_s != null && gt.burn_duration_s != null) {
      rows.push([
        "Burn duration",
        `${num(unified.burn_duration_s, 3)} s`,
        `${num(gt.burn_duration_s, 3)} s`,
        `${num(
          agreement(unified.burn_duration_s, gt.burn_duration_s, 30),
          0
        )}%`,
      ]);
    }
    table(
      st,
      [
        { label: "Metric", width: 52 },
        { label: "Simulation", width: 44, align: "right" },
        { label: "NASA PSI", width: 44, align: "right" },
        { label: "Agreement", width: 38, align: "right" },
      ],
      rows
    );
    paragraph(
      st,
      "Agreement is the relative similarity score used by the Jev panel, not a measurement uncertainty.",
      { size: 7.3, color: C.faint, gap: 2.2 }
    );

    if (match) {
      const runner = match.runner_up;
      const runnerId =
        runner?.test_point ||
        runner?.experiment_id ||
        runner?.accession ||
        "surrogate";
      paragraph(
        st,
        [
          match.matched
            ? `Match pool: ${match.pool === "real" ? "real PSI flight data" : "synthetic surrogate"}`
            : `No PSI match: ${match.reason || "no candidate in this fuel/gravity class"}`,
          match.matched ? `distance ${num(match.distance, 3)}` : null,
          match.matched
            ? `delta O2 ${num(match.deltas?.oxygen_pct, 2)} %, delta P ${num(
                match.deltas?.pressure_bar,
                3
              )} bar, delta u ${num(match.deltas?.velocity_ms, 3)} m/s`
            : null,
          match.matched && runner
            ? `runner-up ${runnerId} at ${num(runner.distance, 3)}`
            : null,
          match.matched
            ? `${match.real_candidates ?? 0} real / ${
                match.synthetic_candidates ?? 0
              } surrogate candidates`
            : null,
          match.extinction_mismatch ? "outcome mismatch penalty +0.15" : null,
        ]
          .filter(Boolean)
          .join("; "),
        { size: 8.1, color: C.muted, gap: 2.4 }
      );
    }
  } else {
    paragraph(
      st,
      "No NASA PSI ground truth matched this run's fuel and gravity class, so the Jev comparison is withheld.",
      { color: C.muted }
    );
  }

  // ---- Burn curve chart ----------------------------------------------------
  if (chartByKey.has("burn-curves")) {
    const [key, title, caption] = CHART_CAPTIONS[0];
    chartFigure(st, 1, chartByKey.get(key), title, caption);
  }

  // ---- Fire safety / Tier 2 ------------------------------------------------
  heading(st, "Fire safety assessment (Tier 2)");
  metricCards(st, [
    {
      label: "Peak temperature",
      value: peakTemp != null ? `${num(peakTemp, 0)} K` : "n/a",
      color: peakTemp > 1800 ? C.warn : C.ink,
    },
    {
      label: "Radiant loss critical",
      value: bool(verdict?.radiant_heat_loss_critical),
      color: safetyFlagColor(verdict?.radiant_heat_loss_critical),
      size: 10.5,
    },
    {
      label: "Flame quenched",
      value: final.quenched == null ? "n/a" : bool(final.quenched),
      color: safetyFlagColor(final.quenched),
      size: 10.5,
    },
    {
      label: "Stability",
      value:
        final.stability != null ? `${num(final.stability, 1)} / 100` : "n/a",
      color: final.stability != null && final.stability < 40 ? C.warn : C.ink,
      size: 10.5,
    },
  ]);

  if (tier2Report) {
    const engineLabel =
      tier2Report.engine === "nanogpt"
        ? `DeepSeek (${tier2Report.engine_model || "NanoGPT"}) on NanoGPT, US-hosted`
        : tier2Report.engine === "azure"
          ? `Azure AI Foundry (${tier2Report.engine_model || "configured model"})`
          : "deterministic local fallback (no frontier model call)";
    paragraph(st, `Synthesis engine: ${engineLabel}.`, {
      size: 8.1,
      color: C.muted,
      gap: 1.4,
    });
    if (tier2Report.notes) {
      paragraph(st, tier2Report.notes, {
        size: 7.5,
        color: C.faint,
        style: "italic",
        gap: 2.4,
      });
    }
    if (tier2Report.markdown) {
      markdownReport(st, tier2Report.markdown);
    } else {
      paragraph(st, "The tier-2 report is empty for this run.", {
        color: C.muted,
      });
    }
    paragraph(
      st,
      "AI-assisted analysis: verify conclusions against the solver diagnostics and NASA PSI source data before operational use.",
      { size: 7.2, color: C.faint, style: "italic", gap: 2 }
    );
  } else {
    paragraph(st, "No tier-2 fire-safety report is attached to this run.", {
      color: C.muted,
    });
  }

  // ---- Suggestions ---------------------------------------------------------
  const suggestions = buildSuggestions(history, final);
  heading(st, "Rule-based run suggestions");
  if (suggestions.length) {
    suggestions.forEach((item) => bullet(st, item));
    st.y += 1.5;
  } else {
    paragraph(st, "No rule-based suggestions for this run.", { color: C.muted });
  }

  // ---- Diagnostic charts ---------------------------------------------------
  heading(st, "Run diagnostics charts");
  let figureNumber = chartByKey.has("burn-curves") ? 2 : 1;
  CHART_CAPTIONS.slice(1).forEach(([key, title, caption]) => {
    const chart = chartByKey.get(key);
    if (!chart) return;
    chartFigure(st, figureNumber, chart, title, caption);
    figureNumber += 1;
  });

  // ---- Solver appendix -----------------------------------------------------
  const diag = final?.diagnostics ?? {};
  const mech = diag.mechanism ?? {};
  heading(st, "Solver diagnostics and mechanism");
  keyValueGrid(st, [
    ["Momentum residual max", sci(diag.momentum_residual_max, 3)],
    [
      "Mass relative error",
      diag.mass_relative_error == null
        ? "n/a"
        : `${num(Number(diag.mass_relative_error) * 100, 2)} %`,
    ],
    [
      "Enthalpy relative change",
      diag.enthalpy_relative_change == null
        ? "n/a"
        : `${num(Number(diag.enthalpy_relative_change) * 100, 2)} %`,
    ],
    ["Substeps total", diag.substeps_total ?? "n/a"],
    ["Substeps capped", diag.substeps_capped == null ? "n/a" : bool(diag.substeps_capped)],
    ["Max drho/rho", sci(diag.max_drho_over_rho, 3)],
    ["Run end time", `${num(diag.run_end_time_s, 4)} s`],
    ["Radial gravity", `${num(diag.radial_gravity_m_per_s2, 3)} m/s2`],
    ["Boundary mass flux", `${sci(diag.boundary_mass_flux_kg_s, 3)} kg/s`],
    ["Reaction", mech.reaction || "n/a"],
    ["Species", Array.isArray(mech.species) ? mech.species.join(", ") : "n/a"],
    [
      "Heat of reaction",
      mech.heat_of_reaction_j_per_mol_fuel == null
        ? "n/a"
        : `${sci(mech.heat_of_reaction_j_per_mol_fuel, 3)} J/mol`,
    ],
    [
      "Reaction orders",
      mech.orders
        ? Object.entries(mech.orders)
            .map(([k, v]) => `${k} ${num(v, 2)}`)
            .join(", ")
        : "n/a",
    ],
    ["Solver", simResult?.solver ?? "n/a"],
    [
      "Radial geometry",
      diag.geometry
        ? `${num(diag.geometry.r_min_m * 1000, 2)} - ${num(
            diag.geometry.r_max_m * 1000,
            2
          )} mm / ${diag.geometry.Nr} cells`
        : "n/a",
    ],
  ]);

  // ---- Footers -------------------------------------------------------------
  const pages = doc.getNumberOfPages();
  for (let page = 1; page <= pages; page++) {
    doc.setPage(page);
    doc.setDrawColor(C.line[0], C.line[1], C.line[2]);
    doc.setLineWidth(0.25);
    doc.line(M, 283.5, PAGE_W - M, 283.5);
    setFont(doc, 6.9, "normal", C.faint);
    doc.text(
      ascii(`T.R.I.A.G.E. | run ${runId} | generated ${generated}`),
      M,
      288
    );
    doc.text(`Page ${page} of ${pages}`, PAGE_W - M, 288, {
      align: "right",
    });
  }

  return {
    doc,
    filename: `TRIAGE_${String(cfg.fuel ?? "run").replace(
      /[^A-Za-z0-9_-]+/g,
      ""
    )}_${runId}_${dateStamp}.pdf`,
  };
}
