#!/usr/bin/env bash
# reset_bria_houdini.sh — Reset Bria Houdini to vanilla state for fresh testing.
# Usage:
#   bash scripts/reset_bria_houdini.sh          # interactive (asks before deleting)
#   bash scripts/reset_bria_houdini.sh --force   # skip confirmation

set -euo pipefail

FORCE=false
if [[ "${1:-}" == "--force" ]]; then
    FORCE=true
fi

BRIA_CONFIG_DIR="$HOME/.bria"
HOUDINI_PREFS_BASE="$HOME/Library/Preferences/houdini"

# ── Collect files to remove ──────────────────────────────────────────────────

to_remove=()

# 1. Bria config directory (~/.bria/)
if [[ -d "$BRIA_CONFIG_DIR" ]]; then
    to_remove+=("$BRIA_CONFIG_DIR")
fi

# 2. Bria package JSON in all Houdini version prefs
for pkg in "$HOUDINI_PREFS_BASE"/*/packages/bria_houdini.json; do
    [[ -f "$pkg" ]] && to_remove+=("$pkg")
done

# 3. Bria dialog caches (COP, COP2, OBJ)
for dialogs_dir in "$HOUDINI_PREFS_BASE"/*/config/Dialogs/*; do
    [[ -d "$dialogs_dir" ]] || continue
    for sub in COP COP2 OBJ; do
        for item in "$dialogs_dir/$sub"/*bria*; do
            [[ -e "$item" ]] && to_remove+=("$item")
        done
    done
done

# ── Show what will be removed ────────────────────────────────────────────────

if [[ ${#to_remove[@]} -eq 0 ]]; then
    echo "Nothing to clean — environment is already vanilla."
    echo ""
    echo "To install Bria tools as a new user:"
    echo "  export HOUDINI_PACKAGE_DIR=/path/to/bria-houdini"
    echo "  # Then launch Houdini"
    exit 0
fi

echo "The following will be removed:"
echo ""
for item in "${to_remove[@]}"; do
    if [[ -d "$item" ]]; then
        echo "  [dir]  $item"
    else
        echo "  [file] $item"
    fi
done
echo ""

# ── Confirm ──────────────────────────────────────────────────────────────────

if [[ "$FORCE" != true ]]; then
    read -rp "Proceed with cleanup? (y/N) " answer
    if [[ ! "$answer" =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
fi

# ── Delete ───────────────────────────────────────────────────────────────────

for item in "${to_remove[@]}"; do
    rm -rf "$item"
    echo "  Removed: $item"
done

echo ""
echo "Done! Environment is now vanilla."

# ── Post-cleanup instructions ────────────────────────────────────────────────

echo ""
echo "Before launching Houdini, also unset these env vars in your shell:"
echo ""
echo "  unset HOUDINI_PACKAGE_DIR"
echo "  unset BRIA_API_KEY_HOUDINI BRIA_API_ENDPOINT BRIA_CONFIG_PATH"
echo "  unset BRIA_LOG_LEVEL BRIA_BOOTSTRAP_PING BRIA_RMBG_ENDPOINT"
echo "  unset USE_BRIA_PROJECT_PATH BRIA_PROJECT_PATH"
echo ""
echo "Launch Houdini now to verify it's clean (no Bria tools should appear)."
echo ""
echo "To re-install as a new user:"
echo "  export HOUDINI_PACKAGE_DIR=/path/to/bria-houdini"
echo "  # Launch Houdini -> Open Bria Dashboard -> Get API Key -> Install"
