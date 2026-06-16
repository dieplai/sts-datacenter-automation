#!/usr/bin/env bash
# hang_watcher.sh — detect a stalled scraper instance and email the operator.
#
# Watches the most recent logs/crawl_*.log for THIS scraper folder. If the
# file's mtime hasn't moved in $HANG_THRESHOLD seconds (default 900 = 15 min),
# fire one email alert and back off for $COOLDOWN seconds before resuming
# checks (avoid spam if the scraper stays stuck).
#
# Run alongside the supervisor in a separate terminal tab:
#   cd /Users/.../52-web-scraper
#   bash scripts/hang_watcher.sh
#
# Customize:
#   HANG_THRESHOLD=600   # 10 min instead of 15
#   POLL_INTERVAL=60     # check every minute (default 30s)
#   COOLDOWN=3600        # 1h between alerts on the same hang (default 30min)
#   bash scripts/hang_watcher.sh
#
# Stops with Ctrl+C. The hang detector is best-effort — it may produce a
# false positive if the scraper is in a slow segment (form fill + login retry
# can take a few minutes). The default 15-min threshold is conservative.

set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

HANG_THRESHOLD="${HANG_THRESHOLD:-900}"
POLL_INTERVAL="${POLL_INTERVAL:-30}"
COOLDOWN="${COOLDOWN:-1800}"

if [[ -x "/opt/anaconda3/bin/python" ]] \
   && /opt/anaconda3/bin/python -c "import smtplib" 2>/dev/null; then
    PY="/opt/anaconda3/bin/python"
else
    PY="python"
fi

TS() { date +%Y-%m-%d_%H:%M:%S; }
log() { printf '[%s] [hang-watcher] %s\n' "$(TS)" "$*"; }

last_alert_ts=0

log "watching $ROOT_DIR/logs/crawl_*.log"
log "HANG_THRESHOLD=${HANG_THRESHOLD}s POLL_INTERVAL=${POLL_INTERVAL}s COOLDOWN=${COOLDOWN}s"

trap 'log "stopped by signal"; exit 0' INT TERM

while true; do
    LATEST_LOG=$(ls -t logs/crawl_*.log 2>/dev/null | head -1)

    if [[ -z "$LATEST_LOG" ]]; then
        log "no log file yet (scraper not started?), sleeping ${POLL_INTERVAL}s"
        sleep "$POLL_INTERVAL"
        continue
    fi

    # Stat mtime in seconds since epoch (BSD/macOS variant).
    MTIME=$(stat -f %m "$LATEST_LOG" 2>/dev/null || stat -c %Y "$LATEST_LOG" 2>/dev/null)
    NOW=$(date +%s)
    AGE=$((NOW - MTIME))

    if [[ $AGE -gt $HANG_THRESHOLD ]]; then
        SINCE_LAST_ALERT=$((NOW - last_alert_ts))
        if [[ $SINCE_LAST_ALERT -gt $COOLDOWN ]]; then
            log "🚨 HANG DETECTED — log idle for ${AGE}s (>${HANG_THRESHOLD}s threshold)"
            log "→ sending email alert"
            "$PY" scripts/notify.py \
                --kind hang \
                --reason "no log update for ${AGE}s (threshold ${HANG_THRESHOLD}s)" \
                --scraper-dir "$ROOT_DIR" \
                --log "$LATEST_LOG" \
                || log "⚠️ email send failed"
            last_alert_ts=$NOW
        else
            log "still hanging (${AGE}s idle), but in cooldown "\
"(next alert in $((COOLDOWN - SINCE_LAST_ALERT))s)"
        fi
    fi

    sleep "$POLL_INTERVAL"
done
