#!/bin/sh
docker run --rm \
  -v "$(pwd):/config" \
  ghcr.io/home-assistant/home-assistant:stable \
  python -m homeassistant --script check_config -c /config