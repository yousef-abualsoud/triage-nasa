import React, { Component, useEffect, useMemo, useState } from "react";
import { useTriageBackend, useConfigForm } from "./hooks.js";
import ControlPanel from "./components/ControlPanel.jsx";
import FlameField2D from "./components/FlameField2D.jsx";
import FlameField3D from "./components/FlameField3D.jsx";
import IterationGraph from "./components/IterationGraph.jsx";
import CalculationLog from "./components/CalculationLog.jsx";
import JevComparison from "./components/JevComparison.jsx";
import MoreGraphs from "./components/MoreGraphs.jsx";

const DEFAULT_CONFIG = {
  fuel: "CH4",
  oxygen_pct: 21.0,
  ambient_pressure_bar: 1.0,
  ambient_temperature_k: 300.0,
  gravity_mode: "zero_g",
  custom_gravity_m_per_s2: 3.7,
  custom_g_jitter_m_per_s2: 0.0,
  inlet_velocity_ms: 0.0,
  ignition_method: "energy_deposition",
  ignition_energy_j: 2.0,
  nx: 128,
  ny: 128,
  dt_s: 0.001,
  iteration_count: 200,
  domain_length_m: 0.08,
  domain_height_m: 0.08,
  ignition_region_m: 0.003,
  output_interval_steps: 4,
};

const TABS = [
  { key: "run", label: "1 · Run & Calculations" },
  { key: "visuals", label: "2 · Fire Visuals & Analysis" },
  { key: "graphs", label: "3 · More Graphs" },
];

/** Render-failure guard: shows the error in-page instead of a blank app. */
class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="error-bar" role="alert">
          UI error: {String(this.state.error?.message ?? this.state.error)}
          <button
            className="action-btn"
            style={{ marginLeft: 12 }}
            onClick={() => this.setState({ error: null })}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const backend = useTriageBackend();
  const { config, update } = useConfigForm(DEFAULT_CONFIG);
  const [frameIndex, setFrameIndex] = useState(0);
  const [viewMode, setViewMode] = useState("3D");
  const [tab, setTab] = useState("run");

  // Initial run once connected.
  useEffect(() => {
    if (backend.connected && !backend.simResult) {
      backend.sendConfig(config);
    }
  }, [backend.connected]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fuel preset list once connected (built-ins + persisted customs).
  useEffect(() => {
    if (backend.connected && !backend.fuelInfo) {
      backend.refreshFuels();
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
  const runId = backend.simResult?.run_id ?? null;
  // Nearest NASA PSI ground truth ships with the triage reply; until triage
  // runs there is no dashed overlay (nothing to compare against yet).
  const groundTruth = useMemo(
    () => backend.verdict?.ground_truth ?? null,
    [backend.verdict]
  );

  const frame = frames[Math.min(frameIndex, frames.length - 1)] ?? null;
  const time = times[Math.min(frameIndex, times.length - 1)] ?? null;

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

      <nav className="tab-nav" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={`tab-btn ${tab === t.key ? "active" : ""}`}
            onClick={() => setTab(t.key)}
            type="button"
          >
            {t.label}
          </button>
        ))}
      </nav>

      {backend.error && (
        <div className="error-bar" role="alert">
          {backend.error}
        </div>
      )}

      <ErrorBoundary key={tab}>
        {tab === "run" && (
          <main className="layout layout-run">
            <aside className="col controls">
              <ControlPanel
                config={config}
                update={update}
                fuelInfo={backend.fuelInfo}
                onSaveFuel={backend.saveFuel}
                onDeleteFuel={backend.deleteFuel}
                onRun={() => backend.sendConfig(config)}
                busy={backend.busy}
              />
            </aside>
            <section className="col main-run">
              <IterationGraph history={history} />
              <CalculationLog
                history={history}
                times={times}
                busy={backend.busy}
                finalData={finalData}
              />
            </section>
          </main>
        )}

        {tab === "visuals" && (
          <main className="layout layout-visuals">
            <section className="col main-viz">
              {viewMode === "3D" ? (
                <FlameField3D
                  frame={frame}
                  time={time}
                  frameIndex={frameIndex}
                  frameCount={frames.length}
                  onScrub={setFrameIndex}
                  gravityMode={config.gravity_mode}
                  finalData={finalData}
                  domain={{
                    L: config.domain_length_m,
                    H: config.domain_height_m,
                  }}
                  ambientK={config.ambient_temperature_k}
                  headerExtra={
                    <ViewToggle mode={viewMode} onChange={setViewMode} />
                  }
                />
              ) : (
                <FlameField2D
                  frame={frame}
                  time={time}
                  frameIndex={frameIndex}
                  frameCount={frames.length}
                  onScrub={setFrameIndex}
                  gravityMode={config.gravity_mode}
                  finalData={finalData}
                  ambientK={config.ambient_temperature_k}
                  headerExtra={
                    <ViewToggle mode={viewMode} onChange={setViewMode} />
                  }
                />
              )}
              <JevComparison
                verdictMsg={backend.verdict}
                sim={unified}
                onTriage={
                  runId ? () => backend.requestTriage(runId) : undefined
                }
                busy={backend.busy}
                connected={backend.connected}
              />
            </section>
            <aside className="col report">
              <div className="panel tier2-panel">
                <div className="panel-head">
                  <h2>Tier 2 — Frontier synthesis</h2>
                  <span className="chip">
                    {backend.tier2Report?.azure
                      ? "Azure AI Foundry"
                      : "local fallback"}
                  </span>
                </div>
                <button
                  className="action-btn primary"
                  onClick={() => backend.requestTier2(runId)}
                  disabled={!backend.connected || backend.busy || !runId}
                >
                  Request Tier 2 report
                </button>
                {backend.tier2Report ? (
                  <MarkdownView markdown={backend.tier2Report.markdown} />
                ) : (
                  <div className="tier2-empty">
                    <p className="muted small">
                      The frontier model synthesizes a fire-safety diagnostic
                      from this run, the nearest NASA PSI comparison, and the
                      tier-1 verdict — with Moon/Mars ECLSS recommendations.
                    </p>
                  </div>
                )}
              </div>
            </aside>
          </main>
        )}

        {tab === "graphs" && (
          <main className="layout layout-graphs">
            <MoreGraphs
              history={history}
              frame={frame}
              frameIndex={frameIndex}
              ambientK={config.ambient_temperature_k}
              finalData={finalData}
              groundTruth={groundTruth}
            />
          </main>
        )}
      </ErrorBoundary>

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

function ViewToggle({ mode, onChange }) {
  return (
    <div className="view-toggle" role="group" aria-label="Flame field view mode">
      {["3D", "2D"].map((m) => (
        <button
          key={m}
          className={`toggle-btn ${mode === m ? "active" : ""}`}
          onClick={() => onChange(m)}
          aria-pressed={mode === m}
          type="button"
        >
          {m}
        </button>
      ))}
    </div>
  );
}

function MarkdownView({ markdown }) {
  // Tiny, dependency-free Markdown-ish renderer for the Tier 2 report.
  const lines = markdown.split("\n");
  const out = [];
  let para = [];
  const inline = (text, keyPrefix) =>
    text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith("**") && part.endsWith("**") ? (
        <strong key={`${keyPrefix}b${i}`}>{part.slice(2, -2)}</strong>
      ) : (
        <React.Fragment key={`${keyPrefix}t${i}`}>{part}</React.Fragment>
      )
    );
  const flushPara = (key) => {
    if (para.length) {
      out.push(<p key={key}>{inline(para.join(" "), key)}</p>);
      para = [];
    }
  };
  lines.forEach((line, i) => {
    if (line.startsWith("## ")) {
      flushPara(`p${i}`);
      out.push(<h3 key={i}>{inline(line.slice(3), `h${i}`)}</h3>);
    } else if (line.startsWith("# ")) {
      flushPara(`p${i}`);
      out.push(<h2 key={i}>{inline(line.slice(2), `h${i}`)}</h2>);
    } else if (line.startsWith("- ")) {
      flushPara(`p${i}`);
      out.push(<li key={i}>{inline(line.slice(2), `l${i}`)}</li>);
    } else if (!line.trim()) {
      flushPara(`p${i}`);
    } else {
      para.push(line);
    }
  });
  flushPara("pEnd");
  return <div className="markdown">{out}</div>;
}