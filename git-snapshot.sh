#!/bin/sh
set -e

cd /config || exit 1

git add -A

if ! git diff --cached --quiet; then
  git commit -m "HA snapshot $(date -Iseconds)"
fi
git push
