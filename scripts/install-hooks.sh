#!/bin/sh
# install-hooks.sh — copies Git hooks into .git/hooks/ and makes them executable.
# Run once after cloning:  sh scripts/install-hooks.sh
#
# Hooks installed:
#   pre-commit  — tsc --noEmit + pyflakes on staged files
#   pre-push    — tsc --noEmit on full frontend tree

set -e

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
HOOKS_SRC="$REPO_ROOT/scripts/hooks"
HOOKS_DST="$REPO_ROOT/.git/hooks"

mkdir -p "$HOOKS_DST"

for hook in pre-commit pre-push; do
  if [ -f "$HOOKS_SRC/$hook" ]; then
    cp "$HOOKS_SRC/$hook" "$HOOKS_DST/$hook"
    chmod +x "$HOOKS_DST/$hook"
    echo "Installed $hook"
  fi
done

echo "Done. Git hooks are active for this clone."
