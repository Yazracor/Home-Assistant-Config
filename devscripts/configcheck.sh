#!/bin/sh
python3 tools/generate_hitzeschutz_manual_map.py || exit 1

docker run --rm \
  -v "$(pwd):/config" \
  ghcr.io/home-assistant/home-assistant:stable \
  python -m homeassistant --script check_config -c /config
