"use client";

import { useEffect, useState } from "react";
import { EventItem, fetchEvents } from "../lib/api";

export default function EventTimeline() {
  const [events, setEvents] = useState<EventItem[]>([]);
  const [classFilter, setClassFilter] = useState("");
  const [error, setError] = useState("");

  async function load() {
    try {
      const params: Record<string, string> = { limit: "50" };
      if (classFilter) params.class = classFilter;
      const data = await fetchEvents(params);
      setEvents(data);
      setError("");
    } catch (e: any) {
      setError(e.message);
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classFilter]);

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong>Event Timeline</strong>
        <input
          placeholder="filter by class"
          value={classFilter}
          onChange={(e) => setClassFilter(e.target.value)}
        />
      </div>
      {error && <p style={{ color: "#b62324" }}>{error}</p>}
      <table style={{ marginTop: 12 }}>
        <thead>
          <tr>
            <th>Time</th>
            <th>Class</th>
            <th>Confidence</th>
            <th>Stream</th>
            <th>BBox</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id}>
              <td>{new Date(e.ts).toLocaleTimeString()}</td>
              <td>{e.class}</td>
              <td>{(e.confidence * 100).toFixed(0)}%</td>
              <td>{e.stream_id?.slice(0, 8)}</td>
              <td>
                {e.bbox ? `${e.bbox.x.toFixed(2)}, ${e.bbox.y.toFixed(2)}` : "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
