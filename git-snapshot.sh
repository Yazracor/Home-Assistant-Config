#!/bin/sh
cd /config || exit 1

git add -A

git diff --cached --quiet && exit 0

git commit -m "HA snapshot $(date -Iseconds)"