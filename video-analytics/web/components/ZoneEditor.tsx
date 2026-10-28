"use client";

import { useEffect, useRef, useState } from "react";
import { Stream, createRule, frameUrl } from "../lib/api";

type Point = [number, number];

export default function ZoneEditor({
  stream,
  onClose,
  onSaved,
}: {
  stream: Stream;
  onClose: () => void;
  onSaved: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [points, setPoints] = useState<Point[]>([]);
  const [name, setName] = useState(`${stream.name} zone`);
  const [classFilter, setClassFilter] = useState("person");
  const [threshold, setThreshold] = useState(1);
  const [dwell, setDwell] = useState(0);
  const [cooldown, setCooldown] = useState(60);
  const [webhook, setWebhook] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const [size, setSize] = useState({ w: 16, h: 9 });

  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (points.length === 0) return;
    const scale = Math.max(1, canvas.width / 640);
    ctx.strokeStyle = "#f0b429";
    ctx.fillStyle = "rgba(240, 180, 41, 0.18)";
    ctx.lineWidth = 2 * scale;
    ctx.beginPath();
    ctx.moveTo(points[0][0] * canvas.width, points[0][1] * canvas.height);
    for (const p of points.slice(1)) {
      ctx.lineTo(p[0] * canvas.width, p[1] * canvas.height);
    }
    if (points.length >= 3) {
      ctx.closePath();
      ctx.fill();
    }
    ctx.stroke();
    for (const p of points) {
      ctx.beginPath();
      ctx.arc(p[0] * canvas.width, p[1] * canvas.height, 4 * scale, 0, Math.PI * 2);
      ctx.fillStyle = "#f0b429";
      ctx.fill();
    }
  }, [points, size]);

  function addPoint(ev: React.MouseEvent<HTMLCanvasElement>) {
    const rect = ev.currentTarget.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height));
    setPoints((prev) => [...prev, [Number(x.toFixed(4)), Number(y.toFixed(4))]]);
  }

  async function save() {
    setError("");
    if (points.length < 3) {
      setError("Draw at least 3 points.");
      return;
    }
    setBusy(true);
    try {
      await createRule({
        stream_id: stream.id,
        name,
        class_filter: classFilter || null,
        zone_polygon: points,
        threshold_count: threshold,
        dwell_seconds: dwell,
        cooldown_seconds: cooldown,
        webhook_url: webhook || null,
      });
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to save rule");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="row">
          <h2 style={{ margin: 0 }}>Draw zone: {stream.name}</h2>
          <button className="btn secondary" onClick={onClose}>
            Close
          </button>
        </div>
        <p className="muted">
          Click the frame to add polygon points. Coordinates are normalized, so the
          rule works at any resolution.
        </p>
        <div
          className="zone-frame"
          style={{ aspectRatio: `${size.w} / ${size.h}` }}
        >
          <img
            src={frameUrl(stream.id, tick)}
            alt="zone source"
            onLoad={(event) => {
              const img = event.currentTarget;
              if (img.naturalWidth && img.naturalHeight) {
                setSize({ w: img.naturalWidth, h: img.naturalHeight });
              }
            }}
          />
          <canvas
            ref={canvasRef}
            width={size.w}
            height={size.h}
            onClick={addPoint}
          />
        </div>
        <div className="row" style={{ marginTop: 6 }}>
          <span className="muted">{points.length} points</span>
          <div>
            <button
              className="btn secondary"
              onClick={() => setPoints((p) => p.slice(0, -1))}
              disabled={!points.length}
            >
              Undo
            </button>
            <button
              className="btn secondary"
              onClick={() => setPoints([])}
              disabled={!points.length}
            >
              Clear
            </button>
          </div>
        </div>
        <div className="form-grid" style={{ marginTop: 12 }}>
          <label>
            Rule name
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Class filter
            <input
              value={classFilter}
              placeholder="person (blank = any)"
              onChange={(e) => setClassFilter(e.target.value)}
            />
          </label>
          <label>
            Count threshold
            <input
              type="number"
              min={1}
              value={threshold}
              onChange={(e) => setThreshold(Math.max(1, Number(e.target.value)))}
            />
          </label>
          <label>
            Dwell seconds
            <input
              type="number"
              min={0}
              value={dwell}
              onChange={(e) => setDwell(Math.max(0, Number(e.target.value)))}
            />
          </label>
          <label>
            Cooldown seconds
            <input
              type="number"
              min={0}
              value={cooldown}
              onChange={(e) => setCooldown(Math.max(0, Number(e.target.value)))}
            />
          </label>
          <label>
            Webhook URL (optional)
            <input
              value={webhook}
              placeholder="https://example.com/hook"
              onChange={(e) => setWebhook(e.target.value)}
            />
          </label>
        </div>
        {error && <p className="bad">{error}</p>}
        <div className="row" style={{ marginTop: 12 }}>
          <span className="muted">
            Alert when {classFilter || "any object"} count ≥ {threshold}
            {dwell ? ` for ${dwell}s` : ""}.
          </span>
          <button className="btn" onClick={save} disabled={busy || points.length < 3}>
            {busy ? "Saving…" : "Save rule"}
          </button>
        </div>
      </div>
    </div>
  );
}
