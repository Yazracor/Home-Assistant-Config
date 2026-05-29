#!/bin/sh
set -eu

PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/bin:/config:${PATH:-}"
export PATH

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
env_file="$repo_root/.knx-area-assignment.env"
marker_file="$repo_root/.pending_knx_area_assignment"
lock_dir="$repo_root/.pending_knx_area_assignment.lock"

if [ -f "$env_file" ]; then
  # shellcheck disable=SC1090
  . "$env_file"
fi

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
  if [ -n "${PYTHON_BIN:-}" ]; then
    if [ -x "$PYTHON_BIN" ]; then
      printf '%s\n' "$PYTHON_BIN"
      return 0
    fi
    if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
      command -v "$PYTHON_BIN"
      return 0
    fi
  fi

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
    /usr/bin/python \
    /opt/venv/bin/python3 \
    /opt/venv/bin/python \
    /srv/homeassistant/bin/python3 \
    /srv/homeassistant/bin/python \
    /config/venv/bin/python3 \
    /config/venv/bin/python
  do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

print_python_diagnostics() {
  echo "Python diagnostics:"
  echo "  PATH=$PATH"
  echo "  repo_root=$repo_root"
  echo "  env_file=$env_file"
  echo "  PWD=$(pwd)"
  echo "  user=$(id 2>/dev/null || true)"
  echo "  OS:"
  if [ -r /etc/os-release ]; then
    sed 's/^/    /' /etc/os-release
  else
    echo "    /etc/os-release not readable"
  fi
  echo "  Available control/download tools:"
  for cmd in ha curl wget git find ls which command apk apt apt-get bash sh; do
    if command -v "$cmd" >/dev/null 2>&1; then
      printf '    %-8s %s\n' "$cmd" "$(command -v "$cmd")"
    fi
  done
  echo "  Complete file tree from /:"
  if command -v find >/dev/null 2>&1; then
    find / -print 2>/dev/null | sort | sed 's/^/    /'
  else
    echo "    find not available"
  fi
  echo "  If no Python path is listed above, this Git hook environment does not contain Python."
  echo "  In that case, run the assignment from an environment with Python or install Python in this add-on/container."
}

python_bin="$(find_python || true)"
if [ -z "$python_bin" ]; then
  print_python_diagnostics
  echo "python not found; set PYTHON_BIN in $env_file or in the hook environment. PATH=$PATH" >&2
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
  url="$supervisor_endpoint/core/$action"
  if command -v curl >/dev/null 2>&1; then
    curl --fail --silent --show-error \
      --max-time 600 \
      -X POST \
      -H "Authorization: Bearer $supervisor_token" \
      "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- \
      --timeout=600 \
      --header="Authorization: Bearer $supervisor_token" \
      --post-data='' \
      "$url"
  else
    echo "Neither curl nor wget is available for Supervisor API calls." >&2
    exit 1
  fi
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
