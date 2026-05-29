#!/bin/sh
set -eu

repo_root="$(git rev-parse --show-toplevel)"
hooks_dir="$repo_root/.git/hooks"

install -m 755 "$repo_root/devscripts/post-merge" "$hooks_dir/post-merge"

echo "Installed Git hook: $hooks_dir/post-merge"
