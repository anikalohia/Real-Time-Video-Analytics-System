"use client";

import { useEffect, useState } from "react";
import { AlertItem, WS_URL, fetchAlerts } from "../lib/api";

export default function AlertPanel() {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchAlerts()
      .then((page) => setAlerts(page.items))
      .catch((err) => setError(err instanceof Error ? err.message : "failed to load alerts"));
    const ws = new WebSocket(`${WS_URL}/ws/alerts`);
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        setAlerts((prev) => [data, ...prev].slice(0, 100));
      } catch {
        // ignore malformed messages
      }
    };
    const keep = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, 15000);
    return () => {
      clearInterval(keep);
      ws.close();
    };
  }, []);

  return (
    <div className="card">
      <div className="row">
        <strong>Alerts</strong>
        <span className="badge stopped">{alerts.length}</span>
      </div>
      {error && <p className="bad">{error}</p>}
      {alerts.length === 0 && <p className="muted">No alerts yet.</p>}
      <ul className="alert-list">
        {alerts.map((a, i) => (
          <li key={a.id || i}>
            <span className="bad">▲</span>{" "}
            {String(a.payload?.message || a.payload?.rule_name || "Alert")} ·{" "}
            {a.ts ? new Date(a.ts).toLocaleTimeString() : "now"}
            {a.delivered === false && <span className="muted"> · webhook pending</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
