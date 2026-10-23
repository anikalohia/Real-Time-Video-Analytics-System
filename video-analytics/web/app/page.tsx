"use client";

import { useEffect, useState } from "react";
import { Stream, fetchStreams, createStream, API_URL } from "../lib/api";
import StreamGrid from "../components/StreamGrid";
import EventTimeline from "../components/EventTimeline";
import AlertPanel from "../components/AlertPanel";

export default function Home() {
  const [streams, setStreams] = useState<Stream[]>([]);
  const [name, setName] = useState("");
  const [source, setSource] = useState("");
  const [error, setError] = useState("");

  async function load() {
    try {
      setStreams(await fetchStreams());
      setError("");
    } catch (e: any) {
      setError(`Cannot reach API at ${API_URL}`);
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  async function onAdd() {
    if (!name || !source) return;
    await createStream(name, source);
    setName("");
    setSource("");
    load();
  }

  return (
    <main className="container">
      <h1>Real-Time Video Analytics</h1>
      {error && <p style={{ color: "#b62324" }}>{error}</p>}

      <div className="card" style={{ marginBottom: 16 }}>
        <strong>Add stream</strong>
        <div style={{ marginTop: 12 }}>
          <input placeholder="name" value={name} onChange={(e) => setName(e.target.value)} />
          <input
            placeholder="rtsp://... or sample.mp4"
            size={40}
            value={source}
            onChange={(e) => setSource(e.target.value)}
          />
          <button className="btn" onClick={onAdd}>
            Add
          </button>
        </div>
      </div>

      <h2>Streams</h2>
      <StreamGrid streams={streams} />

      <h2 style={{ marginTop: 24 }}>Events & Alerts</h2>
      <div className="grid">
        <EventTimeline />
        <AlertPanel />
      </div>
    </main>
  );
}
