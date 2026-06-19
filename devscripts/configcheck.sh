#!/bin/sh
set -eu

python3 tools/generate_hitzeschutz_manual_map.py --check

docker run --rm \
  -v "$(pwd):/config" \
  ghcr.io/home-assistant/home-assistant:stable \
  python -m homeassistant --script check_config -c /config
