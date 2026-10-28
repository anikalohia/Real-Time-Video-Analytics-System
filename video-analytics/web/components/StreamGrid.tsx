"use client";

import { useEffect, useRef, useState } from "react";
import {
  Detection,
  Stream,
  WS_URL,
  deleteStream,
  frameUrl,
  startStream,
  stopStream,
} from "../lib/api";

type StreamGridProps = {
  streams: Stream[];
  onChanged: () => void;
  onError: (message: string) => void;
  onZone: (stream: Stream) => void;
};

function stateOf(stream: Stream) {
  if (stream.health === "connected") return "connected";
  if (stream.health === "reconnecting") return "reconnecting";
  return stream.status;
}

function StreamView({
  stream,
  onChanged,
  onError,
  onZone,
}: {
  stream: Stream;
  onChanged: () => void;
  onError: (message: string) => void;
  onZone: (stream: Stream) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [connected, setConnected] = useState(false);
  const [frameTick, setFrameTick] = useState(0);
  const [frameOk, setFrameOk] = useState(false);
  const [frameSize, setFrameSize] = useState({ w: 16, h: 9 });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const ws = new WebSocket(`${WS_URL}/ws/streams/${stream.id}`);
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.detections) setDetections(data.detections);
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
  }, [stream.id]);

  useEffect(() => {
    setFrameOk(false);
    setFrameSize({ w: 16, h: 9 });
    const t = setInterval(() => setFrameTick((n) => n + 1), 500);
    return () => clearInterval(t);
  }, [stream.id]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const scale = Math.max(1, canvas.width / 640);
    ctx.lineWidth = 2 * scale;
    ctx.font = `${12 * scale}px sans-serif`;
    for (const d of detections) {
      const x = d.bbox.x * canvas.width;
      const y = d.bbox.y * canvas.height;
      const w = d.bbox.w * canvas.width;
      const h = d.bbox.h * canvas.height;
      ctx.strokeStyle =
        d.class === "person" ? "#2ea043" : d.class === "car" ? "#1f6feb" : "#f0b429";
      ctx.fillStyle = ctx.strokeStyle;
      ctx.strokeRect(x, y, w, h);
      ctx.fillText(
        `${d.class} ${(d.confidence * 100).toFixed(0)}%`,
        x,
        Math.max(12 * scale, y - 4 * scale),
      );
    }
  }, [detections, frameSize]);

  async function action(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : "action failed");
    } finally {
      setBusy(false);
    }
  }

  const state = stateOf(stream);
  const running = stream.status === "running";

  return (
    <div className="card">
      <div className="row">
        <strong>{stream.name}</strong>
        <span className={`badge ${state}`}>{state}</span>
      </div>
      <div
        className="stream-frame"
        style={{ aspectRatio: `${frameSize.w} / ${frameSize.h}` }}
      >
        <img
          src={frameUrl(stream.id, frameTick)}
          alt={`${stream.name} live frame`}
          style={{ opacity: frameOk ? 1 : 0.001 }}
          onLoad={(event) => {
            const img = event.currentTarget;
            if (img.naturalWidth && img.naturalHeight) {
              setFrameSize({ w: img.naturalWidth, h: img.naturalHeight });
            }
            setFrameOk(true);
          }}
          onError={() => setFrameOk(false)}
        />
        {!frameOk && (
          <div className="frame-placeholder">
            {stream.status === "running" ? "waiting for frames…" : "stream stopped"}
          </div>
        )}
        <canvas ref={canvasRef} width={frameSize.w} height={frameSize.h} />
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <span className="muted">
          <span className={connected ? "ok" : "bad"}>●</span> {connected ? "live" : "disconnected"}
          {" · "}
          {detections.length} detections
        </span>
        <span className="muted">{stream.target_fps} FPS target</span>
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <div>
          <button
            className="btn"
            disabled={busy || running}
            onClick={() => action(() => startStream(stream.id))}
          >
            Start
          </button>
          <button
            className="btn secondary"
            disabled={busy || !running}
            onClick={() => action(() => stopStream(stream.id))}
          >
            Stop
          </button>
          <button className="btn secondary" disabled={busy} onClick={() => onZone(stream)}>
            Draw zone
          </button>
        </div>
        <button
          className="btn danger"
          disabled={busy}
          onClick={() => {
            if (!confirm(`Delete stream "${stream.name}"?`)) return;
            action(() => deleteStream(stream.id));
          }}
        >
          Delete
        </button>
      </div>
    </div>
  );
}

export default function StreamGrid({
  streams,
  onChanged,
  onError,
  onZone,
}: StreamGridProps) {
  if (!streams.length) {
    return <p className="muted">No streams registered. Add the demo stream or a looped file.</p>;
  }
  return (
    <div className="grid">
      {streams.map((s) => (
        <StreamView
          key={s.id}
          stream={s}
          onChanged={onChanged}
          onError={onError}
          onZone={onZone}
        />
      ))}
    </div>
  );
}
