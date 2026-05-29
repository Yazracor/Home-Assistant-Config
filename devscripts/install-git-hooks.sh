#!/bin/sh
set -eu

repo_root="$(git rev-parse --show-toplevel)"
hooks_dir="$repo_root/.git/hooks"
hook_file="$hooks_dir/post-merge"

git config pull.rebase false
cat > "$hook_file" <<EOF
#!/bin/sh
set -eu
repo_root="\$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
exec "\$repo_root/devscripts/post-merge" "\$@"
EOF
chmod 755 "$hook_file"

echo "Installed Git hook: $hook_file"
echo "Hook delegates to versioned script: $repo_root/devscripts/post-merge"
echo "Hook log will be written to: $hooks_dir/post-merge.log"
echo "After a pull, the hook starts: $repo_root/devscripts/apply-pending-knx-area-assignments.sh"
echo "Configured git pull strategy: merge (pull.rebase=false)"
