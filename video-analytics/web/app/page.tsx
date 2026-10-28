"use client";

import { useCallback, useEffect, useState } from "react";
import {
  API_URL,
  Stream,
  createStream,
  fetchStreams,
  getToken,
  login,
  logout,
} from "../lib/api";
import StreamGrid from "../components/StreamGrid";
import EventTimeline from "../components/EventTimeline";
import AlertPanel from "../components/AlertPanel";
import ZoneEditor from "../components/ZoneEditor";

export default function Home() {
  const [streams, setStreams] = useState<Stream[]>([]);
  const [name, setName] = useState("");
  const [source, setSource] = useState("");
  const [targetFps, setTargetFps] = useState(10);
  const [error, setError] = useState("");
  const [zoneStream, setZoneStream] = useState<Stream | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loggedIn, setLoggedIn] = useState(false);
  const [showLogin, setShowLogin] = useState(false);

  const load = useCallback(async () => {
    try {
      setStreams(await fetchStreams());
      setError("");
    } catch {
      setError(`Cannot reach API at ${API_URL}`);
    }
  }, []);

  useEffect(() => {
    setLoggedIn(Boolean(getToken()));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  async function onAdd() {
    if (!name || !source) return;
    try {
      await createStream(name, source, targetFps);
      setName("");
      setSource("");
      setError("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to add stream");
    }
  }

  async function onLogin(ev: React.FormEvent) {
    ev.preventDefault();
    try {
      await login(email, password);
      setLoggedIn(true);
      setShowLogin(false);
      setError("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "login failed");
    }
  }

  function onLogout() {
    logout();
    setLoggedIn(false);
  }

  return (
    <main className="container">
      <div className="row" style={{ marginBottom: 16 }}>
        <h1 style={{ margin: 0 }}>Real-Time Video Analytics</h1>
        <div>
          {loggedIn ? (
            <button className="btn secondary" onClick={onLogout}>
              Log out
            </button>
          ) : (
            <button className="btn secondary" onClick={() => setShowLogin((v) => !v)}>
              Admin login
            </button>
          )}
        </div>
      </div>

      {error && <p className="bad">{error}</p>}

      {showLogin && !loggedIn && (
        <form className="card" onSubmit={onLogin} style={{ marginBottom: 16 }}>
          <strong>Admin login</strong>
          <div className="filters" style={{ marginTop: 10 }}>
            <input
              placeholder="admin@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <input
              type="password"
              placeholder="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button className="btn" type="submit">
              Sign in
            </button>
          </div>
          <p className="muted">
            Read-only views work without login. Stream and rule changes need an admin token.
          </p>
        </form>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <strong>Add stream</strong>
        <div className="filters" style={{ marginTop: 12 }}>
          <input
            placeholder="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            placeholder="rtsp://… or /samples/sample.avi"
            size={40}
            value={source}
            onChange={(e) => setSource(e.target.value)}
          />
          <input
            type="number"
            min={1}
            max={60}
            value={targetFps}
            onChange={(e) => setTargetFps(Math.max(1, Number(e.target.value)))}
            style={{ width: 80 }}
          />
          <button className="btn" onClick={onAdd}>
            Add
          </button>
        </div>
        <p className="muted">
          The bundled demo uses <code>rtsp://mediamtx:8554/demo</code>. Use a file path such
          as <code>/samples/sample.avi</code> for a looped clip.
        </p>
      </div>

      <h2>Streams</h2>
      <StreamGrid
        streams={streams}
        onChanged={load}
        onError={setError}
        onZone={setZoneStream}
      />

      <h2 style={{ marginTop: 24 }}>Events &amp; Alerts</h2>
      <div className="grid two">
        <EventTimeline streams={streams} />
        <AlertPanel />
      </div>

      {zoneStream && (
        <ZoneEditor
          stream={zoneStream}
          onClose={() => setZoneStream(null)}
          onSaved={load}
        />
      )}
    </main>
  );
}
