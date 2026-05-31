#!/bin/sh
set -e

cd /config || exit 1

git config user.name "Home Assistant"
git config user.email "homeassistant@homeassistant.local"

git add -A

if ! git diff --cached --quiet; then
  git commit -m "HA snapshot $(date -Iseconds)"
fi

remote_url="$(git remote get-url --push origin 2>/dev/null || git remote get-url origin)"
case "$remote_url" in
  git@github.com:*|ssh://git@github.com/*|ssh://github.com/*)
    ssh_dir="/config/.ssh"
    mkdir -p "$ssh_dir"
    chmod 700 "$ssh_dir"
    touch "$ssh_dir/known_hosts"
    chmod 600 "$ssh_dir/known_hosts"
    if ! ssh-keygen -F github.com -f "$ssh_dir/known_hosts" >/dev/null 2>&1; then
      ssh-keyscan github.com >> "$ssh_dir/known_hosts"
    fi

    ssh_key=""
    if [ -f "$ssh_dir/id_ed25519" ]; then
      ssh_key="$ssh_dir/id_ed25519"
    elif [ -f "$HOME/.ssh/id_ed25519" ]; then
      ssh_key="$HOME/.ssh/id_ed25519"
    elif [ -f "$HOME/.ssh/id_rsa" ]; then
      ssh_key="$HOME/.ssh/id_rsa"
    fi

    if [ -n "$ssh_key" ]; then
      chmod 600 "$ssh_key"
      export GIT_SSH_COMMAND="ssh -i $ssh_key -o IdentitiesOnly=yes -o UserKnownHostsFile=$ssh_dir/known_hosts"
    else
      echo "Missing SSH key: create /config/.ssh/id_ed25519 or /root/.ssh/id_ed25519 and add the matching .pub file as a GitHub deploy key." >&2
      exit 128
    fi
    ;;
esac

git push
