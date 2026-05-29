#!/bin/sh
set -eu

PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/bin:/config:${PATH:-}"
export PATH

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
marker_file="$repo_root/.pending_knx_area_assignment"
lock_dir="$repo_root/.pending_knx_area_assignment.lock"
supervisor_endpoint="${SUPERVISOR_ENDPOINT:-http://supervisor}"
supervisor_token="${SUPERVISOR_TOKEN:-${HASSIO_TOKEN:-}}"
core_control=""
force=0
ha_stopped=0

if [ "${1:-}" = "--force" ]; then
  force=1
fi

if [ "$force" -ne 1 ] && [ ! -f "$marker_file" ]; then
  echo "No pending KNX area assignment marker found: $marker_file"
  exit 0
fi

if ! mkdir "$lock_dir" 2>/dev/null; then
  echo "Another KNX area assignment run is already active: $lock_dir"
  exit 0
fi

cleanup() {
  if [ "$ha_stopped" -eq 1 ]; then
    core_action start
    ha_stopped=0
  fi
  rmdir "$lock_dir" 2>/dev/null || true
}

trap cleanup EXIT

find_python() {
  for candidate in \
    python3 \
    python \
    python3.14 \
    python3.13 \
    python3.12 \
    python3.11 \
    /usr/local/bin/python3 \
    /usr/local/bin/python \
    /usr/local/bin/python3.14 \
    /usr/local/bin/python3.13 \
    /usr/local/bin/python3.12 \
    /usr/local/bin/python3.11 \
    /usr/bin/python3 \
    /usr/bin/python
  do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

python_bin="$(find_python || true)"
if [ -z "$python_bin" ]; then
  echo "python not found in PATH=$PATH" >&2
  exit 1
fi
echo "Using Python: $python_bin"

if [ ! -f "$repo_root/tools/apply_knx_area_assignments.py" ]; then
  echo "tools/apply_knx_area_assignments.py not found" >&2
  exit 1
fi

if command -v ha >/dev/null 2>&1; then
  core_control="ha"
elif [ -n "$supervisor_token" ]; then
  core_control="supervisor_api"
else
  echo "Neither ha nor SUPERVISOR_TOKEN/HASSIO_TOKEN is available; cannot control Home Assistant Core." >&2
  exit 1
fi

supervisor_api() {
  action="$1"
  "$python_bin" - "$supervisor_endpoint/core/$action" "$supervisor_token" <<'PY'
import sys
import urllib.error
import urllib.request

url = sys.argv[1]
token = sys.argv[2]
request = urllib.request.Request(
    url,
    method="POST",
    headers={"Authorization": f"Bearer {token}"},
)

try:
    with urllib.request.urlopen(request, timeout=600) as response:
        body = response.read().decode("utf-8", "replace").strip()
        if body:
            print(body)
except urllib.error.HTTPError as err:
    body = err.read().decode("utf-8", "replace").strip()
    print(f"Supervisor API error {err.code} for {url}: {body}", file=sys.stderr)
    raise SystemExit(1)
except urllib.error.URLError as err:
    print(f"Supervisor API request failed for {url}: {err}", file=sys.stderr)
    raise SystemExit(1)
PY
}

core_action() {
  action="$1"
  if [ "$core_control" = "ha" ]; then
    ha core "$action"
  else
    supervisor_api "$action"
  fi
}

stop_ha() {
  core_action stop
  ha_stopped=1
}

start_ha() {
  core_action start
  ha_stopped=0
}

apply_assignments() {
  "$python_bin" "$repo_root/tools/apply_knx_area_assignments.py" \
    --config-dir "$repo_root" \
    --data-dir "$repo_root"
}

echo "Stopping Home Assistant Core for first registry patch..."
stop_ha
apply_assignments

echo "Starting Home Assistant Core so YAML entity changes are written to the registry..."
start_ha

echo "Stopping Home Assistant Core for second registry patch..."
stop_ha
apply_assignments
rm -f "$marker_file"

echo "Starting Home Assistant Core..."
start_ha
echo "KNX area assignments applied."
