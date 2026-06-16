"""
D:\Dieplai\sts_pipeline_server\01_crawl_tool\scripts\generate_manifest.py
Run after each crawl batch to record SHA256 + row counts per CSV.
Usage: python scripts/generate_manifest.py --account acc1
"""

import argparse
import csv
import hashlib
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
MANIFESTS_DIR = OUTPUT_DIR / "manifests"
SENTINEL = OUTPUT_DIR / ".last_manifest_ts"
LOOKBACK_HOURS = 24


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_rows(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            return max(0, sum(1 for _ in reader) - 1)
    except Exception:
        return 0


def _detect_batch_name(account: str) -> str:
    try:
        cfg = ROOT / "src" / "config" / "_local.py"
        if cfg.is_file():
            ns: dict = {}
            exec(cfg.read_text(encoding="utf-8"), ns)
            batches = ns.get("TRANSACTIONS_BATCH", [])
            if batches:
                return batches[-1].get("name", f"{account}_batch")
    except Exception:
        pass
    return f"{account}_{datetime.now().strftime('%Y%m')}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    args = ap.parse_args()

    now_ts = datetime.now(timezone.utc).timestamp()
    cutoff = now_ts - LOOKBACK_HOURS * 3600
    if SENTINEL.is_file():
        cutoff = max(cutoff, SENTINEL.stat().st_mtime)

    csv_files = [
        f for f in OUTPUT_DIR.rglob("*.csv")
        if f.stat().st_mtime >= cutoff
    ]

    if not csv_files:
        print(f"[manifest] No new CSV files since last manifest.", file=sys.stderr)
        return

    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)

    files_meta = []
    total_rows = 0
    for f in sorted(csv_files):
        rows = _count_rows(f)
        sha = _sha256(f)
        files_meta.append({
            "name": f.name,
            "rows_crawled": rows,
            "size_bytes": f.stat().st_size,
            "sha256": sha,
        })
        total_rows += rows
        print(f"[manifest]   {f.name}: {rows:,} rows  sha256={sha[:12]}...")

    batch_name = _detect_batch_name(args.account)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest = {
        "schema_version": "1.0",
        "account": args.account,
        "server_hostname": socket.gethostname(),
        "batch_name": batch_name,
        "crawl_completed_at": datetime.now().isoformat(),
        "attempt_count": int(os.environ.get("CRAWL_ATTEMPT", "1")),
        "files": files_meta,
        "total_rows_crawled": total_rows,
    }

    out = MANIFESTS_DIR / f"manifest_{args.account}_{ts}.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[manifest] Written: {out.name}  ({len(files_meta)} files, {total_rows:,} rows)")

    SENTINEL.write_text(ts)


if __name__ == "__main__":
    main()
