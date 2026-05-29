#!/bin/sh
set -eu

PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/bin:/config:${PATH:-}"
export PATH

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
marker_file="$repo_root/.pending_knx_area_assignment"
lock_dir="$repo_root/.pending_knx_area_assignment.lock"
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
    ha core start
    ha_stopped=0
  fi
  rmdir "$lock_dir" 2>/dev/null || true
}

trap cleanup EXIT

if ! command -v ha >/dev/null 2>&1; then
  echo "ha command not found; run this on the Home Assistant host or add ha to PATH." >&2
  exit 1
fi

python_bin="$(command -v python3 || command -v python || true)"
if [ -z "$python_bin" ]; then
  echo "python3/python not found" >&2
  exit 1
fi

if [ ! -f "$repo_root/tools/apply_knx_area_assignments.py" ]; then
  echo "tools/apply_knx_area_assignments.py not found" >&2
  exit 1
fi

stop_ha() {
  ha core stop
  ha_stopped=1
}

start_ha() {
  ha core start
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
