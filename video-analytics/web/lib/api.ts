export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

export type Stream = {
  id: string;
  name: string;
  source_url: string;
  status: string;
  health: string;
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
  track_id?: string;
};

export type EventItem = {
  id: number;
  stream_id: string;
  ts: string;
  class: string;
  confidence: number;
  bbox: { x: number; y: number; w: number; h: number };
  track_id?: string;
};

export type AlertItem = {
  id: string;
  rule_id: string;
  stream_id: string;
  ts: string;
  payload: Record<string, unknown>;
  delivered?: boolean;
};

export type Page<T> = {
  items: T[];
  next_cursor: string | null;
};

const TOKEN_KEY = "va_token";

export function getToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token: string) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const r = await fetch(`${API_URL}${path}`, { ...init, headers });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const message =
      body?.error?.message || body?.detail || `request failed (${r.status})`;
    throw new Error(message);
  }
  return body as T;
}

export async function login(email: string, password: string) {
  const data = await request<{ access_token: string; role: string }>(
    "/api/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }) },
  );
  setToken(data.access_token);
  return data;
}

export async function logout() {
  setToken("");
}

export function fetchStreams(): Promise<Stream[]> {
  return request<Stream[]>("/api/streams");
}

export function fetchEvents(
  params: Record<string, string> = {},
): Promise<Page<EventItem>> {
  const qs = new URLSearchParams(params).toString();
  return request<Page<EventItem>>(`/api/events?${qs}`);
}

export function fetchAlerts(): Promise<Page<AlertItem>> {
  return request<Page<AlertItem>>("/api/alerts");
}

export function createStream(
  name: string,
  source_url: string,
  target_fps = 10,
): Promise<Stream> {
  return request<Stream>("/api/streams", {
    method: "POST",
    body: JSON.stringify({ name, source_url, target_fps }),
  });
}

export function startStream(id: string) {
  return request<{ ok: boolean }>(`/api/streams/${id}/start`, {
    method: "POST",
  });
}

export function stopStream(id: string) {
  return request<{ ok: boolean }>(`/api/streams/${id}/stop`, {
    method: "POST",
  });
}

export function deleteStream(id: string) {
  return request<{ ok: boolean }>(`/api/streams/${id}`, { method: "DELETE" });
}

export type RulePayload = {
  stream_id: string;
  name: string;
  class_filter?: string | null;
  zone_polygon?: number[][] | null;
  threshold_count: number;
  dwell_seconds: number;
  cooldown_seconds: number;
  webhook_url?: string | null;
};

export function createRule(payload: RulePayload) {
  return request<{ id: string }>("/api/rules", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function frameUrl(streamId: string, cacheBust = Date.now()) {
  return `${API_URL}/api/streams/${streamId}/frame?t=${cacheBust}`;
}
