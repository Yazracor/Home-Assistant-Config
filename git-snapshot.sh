#!/bin/sh
set -e

cd /config || exit 1

git add -A

if ! git diff --cached --quiet; then
  git commit -m "HA snapshot $(date -Iseconds)"
fi

remote_url="$(git remote get-url --push origin 2>/dev/null || git remote get-url origin)"
case "$remote_url" in
  git@github.com:*|ssh://git@github.com/*|ssh://github.com/*)
    mkdir -p "$HOME/.ssh"
    chmod 700 "$HOME/.ssh"
    touch "$HOME/.ssh/known_hosts"
    chmod 600 "$HOME/.ssh/known_hosts"
    if ! ssh-keygen -F github.com -f "$HOME/.ssh/known_hosts" >/dev/null 2>&1; then
      ssh-keyscan github.com >> "$HOME/.ssh/known_hosts"
    fi
    ;;
esac

git push
