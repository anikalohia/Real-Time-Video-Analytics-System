"use client";

import { useEffect, useState } from "react";
import { WS_URL, fetchAlerts } from "../lib/api";

export default function AlertPanel() {
  const [alerts, setAlerts] = useState<any[]>([]);

  useEffect(() => {
    fetchAlerts().then(setAlerts).catch(() => {});
    let ws: WebSocket | null = new WebSocket(`${WS_URL}/ws/alerts`);
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        setAlerts((prev) => [data, ...prev].slice(0, 50));
      } catch {
        // ignore
      }
    };
    const keep = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, 15000);
    return () => {
      clearInterval(keep);
      ws?.close();
    };
  }, []);

  return (
    <div className="card">
      <strong>Alerts</strong>
      {alerts.length === 0 && <p style={{ color: "#8b949e" }}>No alerts yet.</p>}
      <ul style={{ marginTop: 12, paddingLeft: 18 }}>
        {alerts.map((a, i) => (
          <li key={a.id || i} style={{ marginBottom: 6 }}>
            <span style={{ color: "#f85149" }}>●</span>{" "}
            {a.payload?.message || a.payload?.rule_name || "Alert"} ·{" "}
            {a.ts ? new Date(a.ts).toLocaleTimeString() : "now"}
          </li>
        ))}
      </ul>
    </div>
  );
}
