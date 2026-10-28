#!/usr/bin/env bash
# End-to-end smoke test for the Docker stack.
#
# Requires a running Docker daemon. It is intentionally a *smoke* test: it
# proves the demo stream reaches the dashboard, not that the system is fast.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/docker-compose.yml")
API_URL="${API_URL:-http://localhost:8000}"
WEB_URL="${WEB_URL:-http://localhost:3000}"
KEEP_UP="${KEEP_UP:-0}"
REQUIRE_EVENTS="${REQUIRE_EVENTS:-1}"

PY=()
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys' >/dev/null 2>&1; then
  PY=(python3)
elif command -v py >/dev/null 2>&1 && py -3 -c 'import sys' >/dev/null 2>&1; then
  PY=(py -3)
elif command -v python >/dev/null 2>&1 && python -c 'import sys' >/dev/null 2>&1; then
  PY=(python)
else
  echo "python3/python is required for JSON checks" >&2
  exit 2
fi

docker info >/dev/null 2>&1 || {
  echo "Docker daemon is not available; start Docker Desktop or run scripts/local_pipeline.py instead" >&2
  exit 2
}

cleanup() {
  local status=$?
  if [ "$status" -ne 0 ]; then
    echo "--- compose status ---" >&2
    "${COMPOSE[@]}" ps >&2 || true
    echo "--- recent logs ---" >&2
    "${COMPOSE[@]}" logs --tail=120 >&2 || true
  fi
  if [ "$KEEP_UP" != "1" ]; then
    "${COMPOSE[@]}" down >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT

json_value() {
  "${PY[@]}" - "$1" "$2" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
value = data
for part in sys.argv[2].split("."):
    if isinstance(value, list):
        value = value[int(part)]
    else:
        value = value[part]
print(value)
PY
}

json_item_count() {
  "${PY[@]}" -c 'import json, sys; print(len(json.load(sys.stdin).get("items", [])))'
}

wait_http() {
  local url=$1
  local name=$2
  local attempts=${3:-60}
  local code
  for _ in $(seq 1 "$attempts"); do
    code=$(curl -sS -o /tmp/va-smoke.json -w '%{http_code}' "$url" || true)
    if [ "$code" = "200" ]; then
      return 0
    fi
    sleep 2
  done
  echo "timed out waiting for $name ($url)" >&2
  return 1
}

echo "[smoke] building and starting the stack"
"${COMPOSE[@]}" up -d --build

echo "[smoke] waiting for API health"
wait_http "$API_URL/health" "api health" 90
health_status=$(json_value "$(cat /tmp/va-smoke.json)" "status")
echo "[smoke] api health status: $health_status"

echo "[smoke] waiting for dashboard"
wait_http "$WEB_URL" "web dashboard" 60

echo "[smoke] checking seeded demo stream"
wait_http "$API_URL/api/streams" "streams"
streams_json=$(cat /tmp/va-smoke.json)
stream_id=$(json_value "$streams_json" "0.id")
echo "[smoke] demo stream: $stream_id"

echo "[smoke] waiting for the latest cached frame"
frame_ok=0
for _ in $(seq 1 60); do
  frame_code=$(curl -sS -o /tmp/va-smoke.jpg -w '%{http_code}' \
    "$API_URL/api/streams/$stream_id/frame" || true)
  frame_size=$(wc -c </tmp/va-smoke.jpg 2>/dev/null || echo 0)
  if [ "$frame_code" = "200" ] && [ "$frame_size" -gt 1000 ]; then
    frame_ok=1
    break
  fi
  sleep 2
done
if [ "$frame_ok" != "1" ]; then
  echo "no cached frame was produced for stream $stream_id" >&2
  exit 1
fi
echo "[smoke] latest frame: $frame_size bytes"

echo "[smoke] waiting for events"
events_ok=0
for _ in $(seq 1 45); do
  wait_http "$API_URL/api/events?limit=5" "events"
  events_json=$(cat /tmp/va-smoke.json)
  event_count=$(printf '%s' "$events_json" | json_item_count)
  if [ "$event_count" -gt 0 ]; then
    events_ok=1
    break
  fi
  sleep 2
done
if [ "$events_ok" != "1" ] && [ "$REQUIRE_EVENTS" = "1" ]; then
  echo "no events were produced; set REQUIRE_EVENTS=0 to smoke-test the pipeline without detections" >&2
  exit 1
fi
echo "[smoke] recent events: ${event_count:-0}"

wait_http "$API_URL/api/alerts?limit=5" "alerts"
alerts_json=$(cat /tmp/va-smoke.json)
alert_count=$(printf '%s' "$alerts_json" | json_item_count)
echo "[smoke] recent alerts: $alert_count"

echo "[smoke] PASS"
