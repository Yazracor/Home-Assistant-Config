#!/bin/sh
set -eu

repo_root="$(git rev-parse --show-toplevel)"
hooks_dir="$repo_root/.git/hooks"
post_merge_hook="$hooks_dir/post-merge"
pre_commit_hook="$hooks_dir/pre-commit"

git config pull.rebase false
git config merge.autoEdit false
cat > "$post_merge_hook" <<EOF
#!/bin/sh
set -eu
repo_root="\$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
exec "\$repo_root/devscripts/post-merge" "\$@"
EOF
chmod 755 "$post_merge_hook"

cat > "$pre_commit_hook" <<EOF
#!/bin/sh
set -eu
repo_root="\$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
exec "\$repo_root/devscripts/pre-commit" "\$@"
EOF
chmod 755 "$pre_commit_hook"

echo "Installed Git hook: $post_merge_hook"
echo "Installed Git hook: $pre_commit_hook"
echo "Hook delegates to versioned script: $repo_root/devscripts/post-merge"
echo "Hook delegates to versioned script: $repo_root/devscripts/pre-commit"
echo "Hook log will be written to: $hooks_dir/post-merge.log"
echo "After a pull, the hook starts: $repo_root/devscripts/apply-pending-knx-area-assignments.sh"
echo "Configured git pull strategy: merge (pull.rebase=false)"
echo "Configured git merge editor prompt: disabled (merge.autoEdit=false)"
