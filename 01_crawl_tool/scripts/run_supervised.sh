#!/usr/bin/env bash
# run_supervised.sh — macOS/Linux auto-restart wrapper for the scraper.
#
# Usage:
#   bash scripts/run_supervised.sh
#
# What it does:
#   1. Creates a timestamped log at logs/crawl_YYYYMMDD_HHMMSS.log
#   2. Kills orphan Chrome + chromedriver processes
#   3. Runs `python run.py` with INTERACTIVE_SEARCH=1, stdout+stderr tee'd
#      into the log file (so the operator still sees prompts and can
#      press Enter at segment boundaries)
#   4. On exit code 0: crawl finished cleanly → break loop
#   5. On exit code != 0: wait 10s, cleanup, restart (up to MAX_RESTARTS)
#   6. After MAX_RESTARTS failures in a row: abort with a clear message
#
# The scraper itself picks up where it left off via CSV checkpoint
# (src/storage/checkpoint.py:detect_resume_point), so restarts never
# re-scrape from scratch.

set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MAX_RESTARTS="${MAX_RESTARTS:-30}"
RESTART_COOLDOWN="${RESTART_COOLDOWN:-10}"
mkdir -p logs

# Per-instance Chrome scratch dir. Each scraper folder gets its OWN
# user-data-dir prefix so cleanup_chrome can target only this instance's
# Chrome processes — letting multiple supervisors coexist (e.g. acc1 in
# 52-web-scraper + acc2 in 52-web-scraper-acc2 running in parallel
# without one's restart killing the other's Chrome).
INSTANCE_TMPDIR="$ROOT_DIR/.chrome_tmp"
mkdir -p "$INSTANCE_TMPDIR"

# Pick the right python: user's conda base has selenium; system /usr/bin/python3
# does not. Prefer $PYTHON_BIN if set, then anaconda base, then `python` on PATH.
if [[ -n "${PYTHON_BIN:-}" ]] && [[ -x "$PYTHON_BIN" ]]; then
    PY="$PYTHON_BIN"
elif [[ -x "/opt/anaconda3/bin/python" ]] \
     && /opt/anaconda3/bin/python -c "import selenium" 2>/dev/null; then
    PY="/opt/anaconda3/bin/python"
elif command -v python >/dev/null 2>&1 \
     && python -c "import selenium" 2>/dev/null; then
    PY="python"
else
    echo "FATAL: no python with selenium found (set PYTHON_BIN to override)"
    exit 1
fi

TS() { date +%Y-%m-%d_%H:%M:%S; }
log() { printf '[%s] [supervisor] %s\n' "$(TS)" "$*"; }

cleanup_chrome() {
    # Targeted cleanup: only kill Chrome processes whose user-data-dir
    # is inside THIS instance's $INSTANCE_TMPDIR. Lets two scraper folders
    # run in parallel without one's restart-loop killing the other's
    # Chrome. Chromedriver auto-exits when its Chrome dies (no orphans).
    #
    # Two-pass: SIGTERM, wait, then SIGKILL stragglers — without the
    # SIGKILL pass we sometimes hit "no such window" on the next attempt
    # because Chrome was still releasing its user-data-dir and the new
    # process tried to share it.
    pkill -f "user-data-dir=$INSTANCE_TMPDIR" 2>/dev/null || true
    sleep 2
    pkill -9 -f "user-data-dir=$INSTANCE_TMPDIR" 2>/dev/null || true
    sleep 1
}

# Auto-spawn the hang watcher in the background so the operator doesn't
# need a second terminal. The watcher polls the newest crawl log's mtime
# and emails on stalls. Disable with ENABLE_HANG_WATCHER=0.
HANG_WATCHER_PID=""
if [[ "${ENABLE_HANG_WATCHER:-1}" == "1" ]] && [[ -f scripts/hang_watcher.sh ]]; then
    bash scripts/hang_watcher.sh > logs/hang_watcher.log 2>&1 &
    HANG_WATCHER_PID=$!
    log "🔭 hang_watcher spawned (PID $HANG_WATCHER_PID, log: logs/hang_watcher.log)"
fi

stop_hang_watcher() {
    if [[ -n "$HANG_WATCHER_PID" ]] \
       && kill -0 "$HANG_WATCHER_PID" 2>/dev/null; then
        log "stopping hang_watcher (PID $HANG_WATCHER_PID)"
        kill "$HANG_WATCHER_PID" 2>/dev/null || true
        wait "$HANG_WATCHER_PID" 2>/dev/null || true
    fi
}

trap 'log "Interrupted — killing scraper + chrome"; stop_hang_watcher; cleanup_chrome; exit 130' INT TERM

attempt=0
while [[ $attempt -lt $MAX_RESTARTS ]]; do
    attempt=$((attempt + 1))
    LOG_FILE="logs/crawl_$(date +%Y%m%d_%H%M%S).log"

    log "attempt $attempt/$MAX_RESTARTS — log file: $LOG_FILE"
    cleanup_chrome

    # Auto-pull was removed — it kept prompting the operator for GitHub
    # credentials each restart cycle (HTTPS auth) and was redundant
    # with scripts/sync_siblings.sh which the operator runs explicitly
    # when they want to pick up new fixes. Plus acc2/3/4 aren't git
    # repos at all, so the auto-pull only helped acc1 anyway. Just
    # restart with whatever code is already on disk.

    # Run scraper with stdin still attached to this tty (so INTERACTIVE_SEARCH
    # input() works), duplicating all output into the log file via `tee`.
    # `PIPESTATUS[0]` gives us python's real exit code, not tee's.
    set +e
    # -u (unbuffered) so python's stdout flushes line-by-line through
    # the tee pipe — without it the operator sees nothing for ~10–30s
    # while python imports selenium + boots Chrome, which looks like a
    # hang. PYTHONUNBUFFERED=1 also covers third-party libs.
    #
    # TMPDIR=$INSTANCE_TMPDIR forces undetected_chromedriver to put its
    # Chrome user-data-dir under this folder's .chrome_tmp/, which the
    # cleanup_chrome function uses as its kill filter — so one
    # supervisor's restart can't kill another supervisor's Chrome.
    TMPDIR="$INSTANCE_TMPDIR" \
    INTERACTIVE_SEARCH=1 FAST_API_MODE=1 PYTHONUNBUFFERED=1 \
        "$PY" -u run.py 2>&1 | tee "$LOG_FILE"
    exit_code=${PIPESTATUS[0]}
    set -e

    log "python exited with code $exit_code"

    # Defensive: scraper sometimes exits 0 even when it gave up mid-crawl.
    # Re-classify as crash if the log contains any of the false-completion
    # markers below, so the supervisor will restart instead of treating it
    # as success and stopping the loop.
    FALSE_COMPLETION_PATTERNS=(
        '^\[!\] Error:'                            # run.py outer try/except
        'Soft recovery failed - exiting'           # main_pro_detail give-up
        'DEEP recovery failed:'                    # browser/network died
        'FATAL: Chrome failed to initialize'       # driver couldn't start
        'urlopen error \[Errno 8\]'                # DNS / network outage
        'Max retries exceeded with url:'           # connection refused storm
        'Login error:'                             # login navigation crashed
        'no such window: target window'            # Chrome window died early
        'session not created'                      # chromedriver/Chrome version mismatch
        'Still on login page'                      # login retry exhausted
        'Login failed after .* attempts'           # login retry exhausted (new format)
        'Login form never appeared'                # white-screen of death
        'Core Detail Mode execution failed:'       # src/main.py catch
        'truly no more data'                       # legacy false-complete (now raised, kept for safety)
        'CRITICAL DATA VIOLATION'                  # form filter broken, mid-crawl
        'Date Integrity Violation'                 # same as above, different phrasing
    )
    if [[ $exit_code -eq 0 ]]; then
        # First check: did the crawler actually emit its canonical success
        # marker? If yes, it really did finish — don't penalize earlier
        # transient errors that were already self-healed via recovery.
        # (User-reported bug 2026-04-30: a clean exit at 04:30 with
        # 27,663 records was wrongly reclassified as crash because
        # 'no such window' appeared earlier in the log from a Chrome
        # cleanup pass, even though the crawl completed cleanly afterward.)
        if grep -qF '✅ Detail Mode complete!' "$LOG_FILE" 2>/dev/null; then
            log "✅ Verified canonical success marker — accepting clean exit"
        else
            for pat in "${FALSE_COMPLETION_PATTERNS[@]}"; do
                if grep -qE "$pat" "$LOG_FILE" 2>/dev/null; then
                    log "⚠️ Exit code 0 but log matches '/$pat/' AND no success marker — treating as crash"
                    exit_code=1
                    break
                fi
            done
        fi
    fi

    if [[ $exit_code -eq 0 ]]; then
        log "✅ CRAWL COMPLETE (clean exit). See $LOG_FILE"
        # Email: success notification (so user sees crawl is done).
        if [[ -f scripts/notify.py ]]; then
            "$PY" scripts/notify.py --kind complete \
                --reason "clean exit after $attempt attempts" \
                --scraper-dir "$ROOT_DIR" --log "$LOG_FILE" \
                2>&1 | tee -a "$LOG_FILE" || true
        fi

        # Generate manifest for post-crawl data lineage
        ACCOUNT_NAME="acc1"   # change per machine: acc1 / acc2 / acc3 / acc4
        export CRAWL_ATTEMPT=$attempt
        if [[ -f scripts/generate_manifest.py ]]; then
            "$PY" scripts/generate_manifest.py --account "$ACCOUNT_NAME" \
                2>&1 | tee -a "$LOG_FILE" || true
        fi

        stop_hang_watcher
        cleanup_chrome
        exit 0
    fi

    if [[ $exit_code -eq 130 ]]; then
        log "Interrupted by user (SIGINT). Stopping supervisor."
        stop_hang_watcher
        cleanup_chrome
        exit 130
    fi

    log "⚠️ Crash or error. Sleeping ${RESTART_COOLDOWN}s before restart..."
    sleep "$RESTART_COOLDOWN"
done

log "❌ Hit MAX_RESTARTS=$MAX_RESTARTS. Aborting. Latest log: $LOG_FILE"
# Email: final give-up notification — supervisor exhausted retries,
# operator should investigate. Sent BEFORE cleanup_chrome so the log
# is still attachable.
if [[ -f scripts/notify.py ]]; then
    "$PY" scripts/notify.py --kind max_restarts \
        --reason "Hit MAX_RESTARTS=$MAX_RESTARTS, scraper gave up" \
        --scraper-dir "$ROOT_DIR" --log "$LOG_FILE" \
        2>&1 | tee -a "$LOG_FILE" || true
fi
stop_hang_watcher
cleanup_chrome
exit 1
