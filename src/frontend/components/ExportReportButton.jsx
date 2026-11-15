import React, { useEffect, useRef, useState } from "react";
import MoreGraphs from "./MoreGraphs.jsx";
import { captureReportCharts, expectedReportChartKeys } from "../reportCapture.js";

/**
 * Global report export. The button lives at the far right of the tab strip and
 * stays disabled until both tier-1 triage and the tier-2 fire-safety synthesis
 * exist for the current run. Clicking it renders a dark-theme copy of the
 * Tab-3 charts off-screen, rasterises each SVG, and assembles an A4 PDF with
 * the run configuration, outcome, Jev comparison, tier-2 report, and charts.
 */
export default function ExportReportButton({
  simResult,
  verdictMsg,
  tier2Report,
  busy,
  history,
  frame,
  frameIndex,
  ambientK,
  finalData,
  groundTruth,
  radialFrames,
  finalRadial,
}) {
  const [phase, setPhase] = useState("idle"); // idle | preparing | done
  const [error, setError] = useState(null);
  const hostRef = useRef(null);

  const ready = Boolean(simResult && verdictMsg && tier2Report && !busy);
  const missing = !simResult
    ? "Run a simulation first"
    : !verdictMsg
      ? "Run Tier 1 triage first"
      : !tier2Report
        ? "Generate the Tier 2 report first"
        : busy
          ? "Wait for the current request to finish"
          : null;

  useEffect(() => {
    if (phase !== "preparing") return undefined;
    let cancelled = false;

    const build = async () => {
      try {
        const expected = expectedReportChartKeys({
          history,
          frame,
          finalRadial,
          radialFrames,
        });
        const chartMap = await captureReportCharts(hostRef.current, expected);
        if (cancelled) return;
        const charts = expected
          .filter((key) => chartMap[key])
          .map((key) => ({ key, ...chartMap[key] }));
        // jsPDF is only needed when a report is actually requested; keep it in
        // its own chunk so the dashboard's initial load stays lean.
        const { generateRunReport } = await import("../pdfReport.js");
        const { doc, filename } = generateRunReport({
          simResult,
          verdictMsg,
          tier2Report,
          charts,
        });
        if (cancelled) return;
        doc.save(filename);
        setError(null);
        setPhase("done");
      } catch (err) {
        if (cancelled) return;
        setError(`PDF export failed: ${String(err?.message ?? err)}`);
        setPhase("idle");
      }
    };

    build();
    return () => {
      cancelled = true;
    };
  }, [phase]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (phase !== "done") return undefined;
    const id = window.setTimeout(() => setPhase("idle"), 2200);
    return () => window.clearTimeout(id);
  }, [phase]);

  const label =
    phase === "preparing"
      ? "Preparing PDF…"
      : phase === "done"
        ? "PDF downloaded"
        : "Export PDF";

  return (
    <div className="export-shell">
      <button
        type="button"
        className={`export-btn ${phase === "done" ? "is-done" : ""}`}
        onClick={() => {
          setError(null);
          setPhase("preparing");
        }}
        disabled={!ready || phase === "preparing"}
        title={missing ?? "Download an A4 PDF report for this run"}
        aria-label="Export PDF report"
        data-testid="export-report"
      >
        {label}
      </button>
      {error && (
        <p className="export-error" role="alert">
          {error}
        </p>
      )}
      {phase === "preparing" && (
        <div className="report-render-host" aria-hidden="true" ref={hostRef}>
          <MoreGraphs
            history={history}
            frame={frame}
            frameIndex={frameIndex}
            ambientK={ambientK}
            finalData={finalData}
            groundTruth={groundTruth}
            radialFrames={radialFrames}
            finalRadial={finalRadial}
          />
        </div>
      )}
    </div>
  );
}
