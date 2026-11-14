import { useCallback, useEffect, useRef, useState } from "react";

const WS_URL = (() => {
  // Browser location by default; explicit env override for container/demo setups.
  const override = import.meta.env?.VITE_WS_URL;
  if (override) return override;
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.hostname}:8765`;
})();

/**
 * Full-duplex WebSocket control loop.
 * Sends config/sweep/triage/tier2 envelopes, receives sim_result/sweep_result/
 * triage/tier2_report/error/pong. Auto-reconnects with backoff; keeps latest
 * simResult, sweepResults, verdicts, and tier2 report in state.
 */
export function useTriageBackend() {
  const [connected, setConnected] = useState(false);
  const [simResult, setSimResult] = useState(null);
  const [sweepResults, setSweepResults] = useState(null);
  const [verdict, setVerdict] = useState(null);
  const [tier2Report, setTier2Report] = useState(null);
  const [fuelInfo, setFuelInfo] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const wsRef = useRef(null);
  const pendingRef = useRef(new Map()); // msgId -> resolve fn
  const msgIdRef = useRef(0);

  // Inbound message router: request/response pairs keyed by runId/correlation.
  const routeRef = useRef({
    sim_result: (m) => {
      setSimResult(m);
      setBusy(false);
    },
    sweep_result: (m) => {
      setSweepResults(m);
      setBusy(false);
    },
    triage: (m) => {
      setVerdict(m);
      setBusy(false);
      const res = pendingRef.current.get(m.run_id);
      if (res) {
        res(m);
        pendingRef.current.delete(m.run_id);
      }
    },
    tier2_report: (m) => {
      setTier2Report(m);
      setBusy(false);
      const res = pendingRef.current.get(m.run_id);
      if (res) {
        res(m);
        pendingRef.current.delete(m.run_id);
      }
    },
    fuel_list: (m) => {
      setFuelInfo(m);
      setBusy(false);
      const res = pendingRef.current.get("fuel_list");
      if (res) {
        res(m);
        pendingRef.current.delete("fuel_list");
      }
    },
    fuel_saved: (m) => {
      setFuelInfo(m);
      setBusy(false);
      const res = pendingRef.current.get(`fuel_save:${m.key}`);
      if (res) {
        res(m);
        pendingRef.current.delete(`fuel_save:${m.key}`);
      }
    },
    fuel_deleted: (m) => {
      setFuelInfo(m);
      setBusy(false);
      const res = pendingRef.current.get(`fuel_delete:${m.key}`);
      if (res) {
        res(m);
        pendingRef.current.delete(`fuel_delete:${m.key}`);
      }
    },
    error: (m) => {
      setError(m.message);
      setBusy(false);
      // Reject any pending promise so awaits throw instead of hanging.
      for (const [k, res] of pendingRef.current) {
        res({ __error: m.message });
        pendingRef.current.delete(k);
      }
    },
    pong: () => setBusy(false),
  });

  const connect = useCallback(() => {
    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onopen = () => {
        setConnected(true);
        setError(null);
      };
      ws.onclose = () => {
        setConnected(false);
        setTimeout(connect, 2000);
      };
      ws.onerror = () => setConnected(false);
      ws.onmessage = (evt) => {
        const m = JSON.parse(evt.data);
        routeRef.current[m.kind]?.(m);
      };
    } catch (e) {
      setError(`connection failed: ${e}`);
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connect]);

  const send = useCallback((envelope) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setError("backend not connected");
      return null;
    }
    setBusy(true);
    setError(null);
    ws.send(JSON.stringify(envelope));
    return true;
  }, []);

  // Request the merged fuel preset list (built-ins + persisted customs).
  const refreshFuels = useCallback(() => {
    send({ kind: "fuel_list" });
  }, [send]);

  const sendConfig = useCallback(
    (config) => send({ kind: "config", config }),
    [send]
  );

  const sendSweep = useCallback(
    (sweep, base) => {
      setSweepResults(null);
      return send({ kind: "sweep", sweep, base });
    },
    [send]
  );

  const requestTriage = useCallback(
    (runId) =>
      new Promise((resolve) => {
        pendingRef.current.set(runId, resolve);
        send({ kind: "triage", run_id: runId });
      }),
    [send]
  );

  const requestTier2 = useCallback(
    (runId) =>
      new Promise((resolve) => {
        pendingRef.current.set(runId, resolve);
        send({ kind: "tier2", run_id: runId });
      }),
    [send]
  );

  return {
    connected,
    simResult,
    sweepResults,
    verdict,
    tier2Report,
    fuelInfo,
    error,
    busy,
    sendConfig,
    sendSweep,
    requestTriage,
    requestTier2,
    refreshFuels,
    saveFuel: async (key, data) => {
      const res = await new Promise((resolve) => {
        pendingRef.current.set(`fuel_save:${key}`, resolve);
        send({ kind: "fuel_save", key, data });
      });
      if (res?.__error) throw new Error(res.__error);
      return res;
    },
    deleteFuel: async (key) => {
      const res = await new Promise((resolve) => {
        pendingRef.current.set(`fuel_delete:${key}`, resolve);
        send({ kind: "fuel_delete", key });
      });
      if (res?.__error) throw new Error(res.__error);
      return res;
    },
    clearError: () => setError(null),
  };
}

/**
 * Config form state for the ControlPanel: values, setters, and a plain dict
 * ready to dispatch. Keeps numeric coercions in one place.
 */
export function useConfigForm(initial) {
  const [config, setConfig] = useState(initial);
  const update = useCallback((key, value) => {
    setConfig((c) => ({ ...c, [key]: value }));
  }, []);
  return { config, update, setConfig };
}