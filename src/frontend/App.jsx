import React, { useEffect, useMemo, useState } from "react";
import { useTriageBackend, useConfigForm } from "./hooks.js";
import ControlPanel from "./components/ControlPanel.jsx";
import FlameField2D from "./components/FlameField2D.jsx";
import BurnCurveOverlay from "./components/BurnCurveOverlay.jsx";
import ScatterPlot from "./components/ScatterPlot.jsx";

const DEFAULT_CONFIG = {
  fuel: "CH4",
  oxygen_pct: 21.0,
  ambient_pressure_bar: 1.0,
  ambient_temperature_k: 300.0,
  gravity_mode: "zero_g",
  inlet_velocity_ms: 0.0,
  ignition_method: "energy_deposition",
  ignition_energy_j: 2.0,
  nx: 128,
  ny: 128,
  dt_s: 0.0005,
  end_time_s: 0.5,
  wall_thermal_mode: "adiabatic",
  wall_temperature_k: 300.0,
  domain_length_m: 0.08,
  domain_height_m: 0.08,
  ignition_region_m: 0.003,
  output_interval_steps: 16,
};

const SPECIES = [
  { key: "CH4", label: "Methane (CH₄)" },
  { key: "C2H4", label: "Ethylene (C₂H₄)" },
  { key: "C3H8", label: "Propane (C₃H₈)" },
  { key: "H2", label: "Hydrogen (H₂)" },
];

const GRAVITY_MODES = [
  { key: "zero_g", label: "Zero-G (ideal)" },
  { key: "iss_micro_g", label: "ISS Micro-G (jitter)" },
  { key: "earth_1g", label: "Earth 1G" },
  { key: "mars_g", label: "Mars 0.38G" },
  { key: "moon_g", label: "Moon 0.165G" },
];

export default function App() {
  const backend = useTriageBackend();
  const { config, update } = useConfigForm(DEFAULT_CONFIG);
  const [frameIndex, setFrameIndex] = useState(0);
  const [reportOpen, setReportOpen] = useState(false);

  // Initial run once connected.
  useEffect(() => {
    if (backend.connected && !backend.simResult) {
      backend.sendConfig(config);
    }
  }, [backend.connected]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reset the frame scrubber whenever a new sim result arrives.
  useEffect(() => {
    setFrameIndex(0);
  }, [backend.simResult]);

  const frames = backend.simResult?.frames ?? [];
  const times = backend.simResult?.times ?? [];
  const history = backend.simResult?.history ?? [];
  const unified = backend.simResult?.unified ?? null;
  const finalData = backend.simResult?.final ?? null;
  const groundTruth = useMemo(
    () => findNearestGroundTruth(unified),
    [unified]
  );

  const frame = frames[Math.min(frameIndex, frames.length - 1)] ?? null;

  return (
    <div className="app">
      <header className="app-header">
        <h1>
          T.R.I.A.G.E.
          <span className="subtitle">
            Thermal Reaction Inference &amp; Anomaly Grading Engine
          </span>
        </h1>
        <div className="conn-status">
          <span
            className={`dot ${backend.connected ? "on" : "off"}`}
            aria-hidden="true"
          />
          {backend.connected ? "backend live" : "connecting…"}
          {backend.simResult && (
            <span className="solver-chip">
              solver: {backend.simResult.solver}
            </span>
          )}
        </div>
      </header>

      {backend.error && (
        <div className="error-bar" role="alert">
          {backend.error}
        </div>
      )}

      <main className="layout">
        <aside className="col controls">
          <ControlPanel
            config={config}
            update={update}
            species={SPECIES}
            gravityModes={GRAVITY_MODES}
            onRun={() => backend.sendConfig(config)}
            onSweep={() =>
              backend.sendSweep(
                { oxygen_pct: [14, 18, 21, 25, 30, 40] },
                config
              )
            }
            busy={backend.busy}
          />
        </aside>

        <section className="col main-viz">
          <FlameField2D
            frame={frame}
            time={times[Math.min(frameIndex, times.length - 1)]}
            frameIndex={frameIndex}
            frameCount={frames.length}
            onScrub={setFrameIndex}
            gravityMode={config.gravity_mode}
            finalData={finalData}
          />
          <BurnCurveOverlay
            simHistory={history}
            groundTruth={groundTruth}
          />
          <ScatterPlot
            sweepResults={backend.sweepResults}
            onTriage={async (runId) => {
              const v = await backend.requestTriage(runId);
              if (v?.verdict) {
                setReportOpen(true);
              }
            }}
          />
        </section>

        <aside className="col report">
          <div className="panel verdict-panel">
            <h2>Tier 1 — Jev triage</h2>
            {backend.verdict ? (
              <VerdictView verdict={backend.verdict} />
            ) : (
              <p className="muted">
                Run a simulation, then request triage from the sweep or curve
                panel.
              </p>
            )}
            {unified && (
              <button
                className="action-btn"
                onClick={async () => {
                  await backend.requestTier2(backend.simResult.run_id);
                  setReportOpen(true);
                }}
                disabled={!backend.connected || backend.busy}
              >
                Request Tier 2 report
              </button>
            )}
          </div>
          {backend.tier2Report && reportOpen && (
            <div className="panel tier2-panel">
              <div className="panel-head">
                <h2>Tier 2 — Frontier synthesis</h2>
                <span className="chip">
                  {backend.tier2Report.azure ? "Azure AI Foundry" : "local fallback"}
                </span>
                <button
                  className="close-btn"
                  onClick={() => setReportOpen(false)}
                  aria-label="Close report"
                >
                  ×
                </button>
              </div>
              <MarkdownView markdown={backend.tier2Report.markdown} />
            </div>
          )}
        </aside>
      </main>
      <footer className="app-footer">
        <p>
          NASA Space Apps 2026 — “Flame in Free-Fall”. AI-assisted code &amp;
          data per disclosure rules. Physics: 2D laminar gaseous combustion,
          single-step Arrhenius (reduced approximation).
        </p>
      </footer>
    </div>
  );
}

function VerdictView({ verdict }) {
  const v = verdict.verdict ?? verdict;
  const rows = [
    ["Morphology", v.flame_morphology],
    ["Buoyant convection", String(v.buoyancy_driven_convection)],
    ["Profile match", v.nasa_experiment_profile_match],
    ["Soot score", `${v.soot_volume_fraction_score}/100`],
    ["Radiant loss critical", String(v.radiant_heat_loss_critical)],
    ["Stability", `${v.stability_score}/100`],
    ["Delta", `${v.delta_score}/100`],
    ["Confidence", v.confidence_score],
  ];
  return (
    <table className="verdict-table">
      <tbody>
        {rows.map(([k, val]) => (
          <tr key={k}>
            <th scope="row">{k}</th>
            <td>{val}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function MarkdownView({ markdown }) {
  // Tiny, dependency-free Markdown-ish renderer for the Tier 2 report.
  const lines = markdown.split("\n");
  const out = [];
  let inList = false;
  let para = [];
  const flushPara = (key) => {
    if (para.length) {
      out.push(<p key={key}>{para.join(" ")}</p>);
      para = [];
    }
  };
  lines.forEach((line, i) => {
    if (line.startsWith("## ")) {
      flushPara(`p${i}`);
      out.push(<h3 key={i}>{line.slice(3)}</h3>);
    } else if (line.startsWith("# ")) {
      flushPara(`p${i}`);
      out.push(<h2 key={i}>{line.slice(2)}</h2>);
    } else if (line.startsWith("- ")) {
      flushPara(`p${i}`);
      out.push(<li key={i}>{line.slice(2)}</li>);
      inList = true;
    } else if (!line.trim()) {
      flushPara(`p${i}`);
      inList = false;
    } else {
      para.push(line);
    }
  });
  flushPara("pEnd");
  return <div className="markdown">{out}</div>;
}

function findNearestGroundTruth(unified) {
  // Ground truth arrives with sweep/sim messages in production; for now the
  // backend attaches the closest synthetic PSI run to each verdict. The
  // overlay consumes whatever shape arrives.
  return unified ?? null;
}