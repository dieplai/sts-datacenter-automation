"""Runtime metrics + common exceptions used across the pipeline."""
import time
from datetime import datetime

from .logger import log, format_time_elapsed


class SessionExpired(Exception):
    """Server returned state 3001 (session expired) or 4003 (permission)."""
    def __init__(self, state, message=""):
        super().__init__(f"Session expired (state={state}): {message}")
        self.state = state


class ApiError(Exception):
    """Server returned a non-zero, non-session error state, or HTTP failure."""
    def __init__(self, state, message=""):
        super().__init__(f"API error (state={state}): {message}")
        self.state = state


class RateMeter:
    """Track records/minute, success/error rate; emit a log line every `window_sec`."""
    def __init__(self, window_sec=30, label="fetch"):
        self.window = window_sec
        self.label = label
        self.start = time.time()
        self.count = 0
        self.errors = 0
        self._last_emit = self.start

    def tick(self, ok=True):
        self.count += 1
        if not ok:
            self.errors += 1
        now = time.time()
        if now - self._last_emit >= self.window:
            elapsed = now - self.start
            rps = self.count / elapsed if elapsed > 0 else 0
            rpm = rps * 60
            err = self.errors / max(self.count, 1)
            log(
                f"[~] [{self.label}] {rpm:.0f} rec/min | {rps:.1f} rps | "
                f"err={err:.1%} | total={self.count}",
                "INFO",
            )
            self._last_emit = now

    def snapshot(self):
        elapsed = time.time() - self.start
        rps = self.count / elapsed if elapsed > 0 else 0
        return {
            "label": self.label,
            "elapsed_sec": elapsed,
            "count": self.count,
            "errors": self.errors,
            "rps": rps,
            "rpm": rps * 60,
            "error_rate": self.errors / max(self.count, 1),
        }


class Timer:
    """Track total run + aggregated named intervals for a performance report."""
    def __init__(self):
        self.checkpoints = {}
        self.start_time = datetime.now()
        self.intervals = {}
        self.active_intervals = {}

    def checkpoint(self, name):
        elapsed = (datetime.now() - self.start_time).total_seconds()
        self.checkpoints[name] = elapsed

    def start_interval(self, name):
        self.active_intervals[name] = time.time()

    def stop_interval(self, name):
        if name in self.active_intervals:
            duration = time.time() - self.active_intervals[name]
            self.intervals.setdefault(name, []).append(duration)
            del self.active_intervals[name]

    def print_performance(self, transactions=None):
        print(f"\n{'='*60}")
        print("[~] PERFORMANCE REPORT")
        print(f"{'='*60}")

        total_run_time = (datetime.now() - self.start_time).total_seconds()
        print(f"[i] Total run time: {format_time_elapsed(total_run_time)}")
        print(f"{'-'*60}")

        if transactions:
            total_records = len(transactions)
            print("\n[i] SUMMARY:")
            print(f"   Total records: {total_records:,}")

            hours = total_run_time / 3600
            if hours > 0 and total_records:
                records_per_hour = total_records / hours
                pages_per_hour = (total_records / 20) / hours
                print(f"   Speed: {records_per_hour:.0f} records/hour")
                print(f"   Speed: {pages_per_hour:.1f} pages/hour")
                print(f"   Avg:   {total_run_time/total_records:.2f}s/record")

            try:
                from .. import config
                expected = getattr(config, "SEARCH_EXPECTED_TOTAL", None)
                if expected and hours > 0:
                    remaining = expected - total_records
                    if remaining > 0 and records_per_hour > 0:
                        est_hours = remaining / records_per_hour
                        print("\n[~] ETA:")
                        print(f"   Remaining: {remaining:,} records")
                        print(f"   Est. time: {format_time_elapsed(est_hours * 3600)}")
            except Exception:
                pass

        print(f"\n{'-'*60}")

        if self.intervals:
            print("\n[i] TIME BREAKDOWN:")
            print(f"{'OPERATION':<25} | {'TOTAL (s)':<10} | {'AVG (s)':<8} | {'% TOTAL':<8}")
            print(f"{'-'*60}")

            sorted_intervals = sorted(
                self.intervals.items(), key=lambda x: sum(x[1]), reverse=True,
            )
            for name, durations in sorted_intervals:
                total = sum(durations)
                count = len(durations)
                avg = total / count if count > 0 else 0
                pct = (total / total_run_time) * 100 if total_run_time else 0
                print(f"{name:<25} | {total:<10.2f} | {avg:<8.3f} | {pct:<7.1f}%")
        else:
            print("\n[-] Interval tracking not enabled.")

        print(f"{'='*60}")
