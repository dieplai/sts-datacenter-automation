#!/usr/bin/env bash
# sync_siblings.sh — pull latest code (git) and broadcast to all sibling
# scraper folders matching `52-web-scraper*` in the parent directory.
#
# Run from the canonical (git) instance:
#   cd /Users/jamesgatsby/tai_prompt_idea/52-web-scraper
#   bash scripts/sync_siblings.sh
#
# What it does:
#   1. `git pull origin tai_code_prompt` in this folder (if .git/ present)
#   2. For each sibling folder named `52-web-scraper*`, rsync the code
#      directories (src/, scripts/, run.py, RUNBOOK.md) over.
#
# What it PRESERVES per sibling (never overwrites):
#   - src/config/_local.py     (per-account creds + HS code)
#   - output/                  (CSVs and Excel)
#   - logs/                    (crawl logs, hang_watcher logs)
#   - .chrome_tmp/             (Chrome user-data-dir)
#   - .drive_folder_id         (cached Drive folder ID)
#
# Net effect: edit code once in the canonical folder, run this script, all
# siblings on this machine pick up the new code immediately. Running
# scrapers don't need to restart — Python only loads files at process
# start, so the change applies on the next supervisor restart cycle.
#
# For the 2-machine setup: run this same script on EACH machine after
# pulling. Each machine has its own canonical (git clone) + siblings.

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
PARENT="$(dirname "$ROOT_DIR")"
THIS_NAME="$(basename "$ROOT_DIR")"

TS() { date +%H:%M:%S; }
log() { printf '[%s] [sync] %s\n' "$(TS)" "$*"; }

# ─── Step 1: git pull (if this is a git repo) ────────────────────────
if [[ -d "$ROOT_DIR/.git" ]]; then
    log "📥 git pull in $THIS_NAME..."
    git pull origin tai_code_prompt
else
    log "ℹ️ $THIS_NAME is not a git repo — skipping git pull. Run this "
    log "   script from the folder that IS a git clone instead."
fi

# ─── Step 2: rsync code to siblings ──────────────────────────────────
# Top-level files + directories to sync. Each entry is preserved-as-is
# (no rename, no merge); --delete removes files in the sibling that no
# longer exist in canonical (e.g. when we delete a deprecated .py).
SYNC_PATHS=(
    "src/scraper"
    "src/extract"
    "src/storage"
    "src/core"
    "src/nav"
    "src/parsing"
    "src/observability"
    "src/utils.py"
    "src/main.py"
    "src/__init__.py"
    "src/config/__init__.py"
    "src/config/auth.py"
    "src/config/proxy.py"
    "src/config/scrape_filters.py"
    "src/config/settings.py"
    "src/config/_local.example.py"
    "scripts"
    "run.py"
    "RUNBOOK.md"
)

# rsync excludes for safety — these patterns are NEVER copied to siblings
# (so each sibling keeps its own state). With --delete on, anything not
# in canonical gets removed from siblings UNLESS listed here.
RSYNC_EXCLUDES=(
    "__pycache__"
    "*.pyc"
    ".chrome_tmp"
    "_local.py"          # per-account creds
    ".drive_folder_id"   # per-instance cache
    "crawl_monthly.sh"   # acc5-only orchestrator (large date-range buyer query
                         # needs month chunking; acc1-4 do months manually so
                         # don't need it). Exclude so sync doesn't wipe the
                         # acc5 copy when canonical has no monthly script.
    "crawl_daily_aggregate_monthly.py"
                         # acc5-only day-by-day orchestrator that aggregates
                         # 28-31 day scrapes into one monthly CSV before
                         # Drive upload. Avoids 52wmb's wide-query
                         # pagination instability. Exclude so sibling sync
                         # doesn't wipe the acc5 copy.
)

EXCLUDE_ARGS=()
for ex in "${RSYNC_EXCLUDES[@]}"; do
    EXCLUDE_ARGS+=(--exclude="$ex")
done

count=0
for sibling in "$PARENT"/52-web-scraper*; do
    sibling_name=$(basename "$sibling")
    [[ "$sibling_name" == "$THIS_NAME" ]] && continue
    [[ -d "$sibling" ]] || continue

    log "📤 → $sibling_name"
    for path in "${SYNC_PATHS[@]}"; do
        src_path="$ROOT_DIR/$path"
        dst_path="$sibling/$path"
        [[ -e "$src_path" ]] || continue

        if [[ -d "$src_path" ]]; then
            # Directory: rsync recursively, --delete to mirror exactly
            mkdir -p "$dst_path"
            rsync -a --delete "${EXCLUDE_ARGS[@]}" \
                  "$src_path/" "$dst_path/"
        else
            # File: simple copy
            mkdir -p "$(dirname "$dst_path")"
            cp -p "$src_path" "$dst_path"
        fi
    done

    # Make scripts executable in the sibling (rsync preserves mode but
    # belt-and-suspenders).
    chmod +x "$sibling"/scripts/*.sh 2>/dev/null || true
    chmod +x "$sibling"/scripts/*.py 2>/dev/null || true

    count=$((count + 1))
done

log "✅ synced $count sibling(s) from $THIS_NAME"
log ""
log "Running scrapers will pick up the new code on their next supervisor"
log "restart attempt (every crash/recovery cycle does an auto-pull). To"
log "force-pickup immediately, Ctrl+C the supervisor terminal and"
log "re-launch."
