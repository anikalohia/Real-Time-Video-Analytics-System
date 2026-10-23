export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

export type Stream = {
  id: string;
  name: string;
  source_url: string;
  status: string;
  target_fps: number;
  created_at: string;
};

export type Detection = {
  stream_id: string;
  frame_id?: number;
  ts: number;
  class: string;
  confidence: number;
  bbox: { x: number; y: number; w: number; h: number };
};

export type EventItem = {
  id: number;
  stream_id: string;
  ts: string;
  class: string;
  confidence: number;
  bbox: { x: number; y: number; w: number; h: number };
};

export async function fetchStreams(): Promise<Stream[]> {
  const r = await fetch(`${API_URL}/api/streams`);
  if (!r.ok) throw new Error("failed streams");
  return r.json();
}

export async function fetchEvents(params: Record<string, string> = {}): Promise<EventItem[]> {
  const qs = new URLSearchParams(params).toString();
  const r = await fetch(`${API_URL}/api/events?${qs}`);
  if (!r.ok) throw new Error("failed events");
  return r.json();
}

export async function fetchAlerts() {
  const r = await fetch(`${API_URL}/api/alerts`);
  if (!r.ok) throw new Error("failed alerts");
  return r.json();
}

export async function createStream(name: string, source_url: string) {
  const r = await fetch(`${API_URL}/api/streams`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, source_url }),
  });
  if (!r.ok) throw new Error("failed create");
  return r.json();
}
