"use client";

import { useEffect, useRef, useState } from "react";
import { Stream, Detection, WS_URL } from "../lib/api";

function StreamView({ stream }: { stream: Stream }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const ws = new WebSocket(`${WS_URL}/ws/streams/${stream.id}`);
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.detections) setDetections(data.detections);
      } catch {
        // ignore
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
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "#2ea043";
    ctx.fillStyle = "#2ea043";
    ctx.lineWidth = 2;
    ctx.font = "12px sans-serif";
    for (const d of detections) {
      const x = d.bbox.x * canvas.width;
      const y = d.bbox.y * canvas.height;
      const w = d.bbox.w * canvas.width;
      const h = d.bbox.h * canvas.height;
      ctx.strokeRect(x, y, w, h);
      ctx.fillText(`${d.class} ${(d.confidence * 100).toFixed(0)}%`, x, Math.max(12, y - 4));
    }
  }, [detections]);

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong>{stream.name}</strong>
        <span className={`badge ${stream.status}`}>{stream.status}</span>
      </div>
      <div style={{ position: "relative", marginTop: 12, background: "#000", aspectRatio: "16/9" }}>
        <canvas ref={canvasRef} width={640} height={360} style={{ width: "100%", height: "100%" }} />
      </div>
      <div style={{ fontSize: 12, marginTop: 8, color: connected ? "#2ea043" : "#b62324" }}>
        {connected ? "live" : "disconnected"} · {detections.length} detections
      </div>
    </div>
  );
}

export default function StreamGrid({ streams }: { streams: Stream[] }) {
  if (!streams.length) return <p>No streams registered.</p>;
  return (
    <div className="grid">
      {streams.map((s) => (
        <StreamView key={s.id} stream={s} />
      ))}
    </div>
  );
}
