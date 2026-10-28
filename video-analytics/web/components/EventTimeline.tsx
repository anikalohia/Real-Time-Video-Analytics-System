"use client";

import { useCallback, useEffect, useState } from "react";
import { EventItem, Stream, fetchEvents } from "../lib/api";

export default function EventTimeline({ streams }: { streams: Stream[] }) {
  const [events, setEvents] = useState<EventItem[]>([]);
  const [classFilter, setClassFilter] = useState("");
  const [streamFilter, setStreamFilter] = useState("");
  const [fromTs, setFromTs] = useState("");
  const [toTs, setToTs] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(
    async (append = false) => {
      setLoading(true);
      try {
        const params: Record<string, string> = { limit: "50" };
        if (classFilter) params.class = classFilter;
        if (streamFilter) params.stream_id = streamFilter;
        if (fromTs) params.from_ts = new Date(fromTs).toISOString();
        if (toTs) params.to_ts = new Date(toTs).toISOString();
        if (append && cursor) params.cursor = cursor;
        const page = await fetchEvents(params);
        setEvents((prev) => (append ? [...prev, ...page.items] : page.items));
        setCursor(page.next_cursor);
        setError("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "failed to load events");
      } finally {
        setLoading(false);
      }
    },
    [classFilter, streamFilter, fromTs, toTs, cursor],
  );

  useEffect(() => {
    setCursor(null);
    const t = setTimeout(() => load(false), 250);
    return () => clearTimeout(t);
  }, [classFilter, streamFilter, fromTs, toTs]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="card">
      <div className="row">
        <strong>Event Timeline</strong>
        <button className="btn secondary" onClick={() => load(false)} disabled={loading}>
          Refresh
        </button>
      </div>
      <div className="filters">
        <input
          placeholder="class (person, car…)"
          value={classFilter}
          onChange={(e) => setClassFilter(e.target.value)}
        />
        <select value={streamFilter} onChange={(e) => setStreamFilter(e.target.value)}>
          <option value="">all streams</option>
          {streams.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <label className="muted">
          from{" "}
          <input
            type="datetime-local"
            value={fromTs}
            onChange={(e) => setFromTs(e.target.value)}
          />
        </label>
        <label className="muted">
          to{" "}
          <input
            type="datetime-local"
            value={toTs}
            onChange={(e) => setToTs(e.target.value)}
          />
        </label>
      </div>
      {error && <p className="bad">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Class</th>
              <th>Confidence</th>
              <th>Stream</th>
              <th>Track</th>
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
                <td>{e.track_id || "-"}</td>
                <td>
                  {e.bbox
                    ? `${e.bbox.x.toFixed(2)}, ${e.bbox.y.toFixed(2)}`
                    : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!events.length && !loading && <p className="muted">No events yet.</p>}
      <div className="row" style={{ marginTop: 10 }}>
        <span className="muted">{events.length} events</span>
        {cursor && (
          <button className="btn secondary" onClick={() => load(true)} disabled={loading}>
            {loading ? "Loading…" : "Load more"}
          </button>
        )}
      </div>
    </div>
  );
}
