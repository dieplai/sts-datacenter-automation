#!/usr/bin/env python3
"""Email notification helper for the 52wmb scraper.

Sends alerts to NOTIFY_TO_EMAIL via Gmail SMTP when:
  - Supervisor hits MAX_RESTARTS (called from run_supervised.sh)
  - Scraper raises an unhandled exception (called from core_pro_detail)
  - Hang watcher detects a stalled crawl (called from hang_watcher.sh)
  - Final clean exit (success notification, optional)

Required env (set in .zshrc or supervisor wrapper):
  NOTIFY_SMTP_USER  — gmail address sending the alert (e.g. mybot@gmail.com)
  NOTIFY_SMTP_PASS  — Gmail "App Password" (16 chars, NOT regular password)
                      https://myaccount.google.com/apppasswords
  NOTIFY_TO_EMAIL   — recipient (default: jamesgatsby92@gmail.com)

Optional:
  NOTIFY_DISABLE=1  — skip email entirely (for testing)

CLI usage (from supervisor):
  python scripts/notify.py --kind crash --reason "MAX_RESTARTS hit" \
      --log /path/to/crawl_xxx.log --account vtic --hs 52
"""
import argparse
import os
import smtplib
import socket
import sys
import traceback
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


def _config_loaded():
    """Read NOTIFY_SMTP_USER / PASS from env, or fall back to a
    config file at ~/.notify-config that has KEY=VALUE lines."""
    user = os.environ.get("NOTIFY_SMTP_USER", "").strip()
    password = os.environ.get("NOTIFY_SMTP_PASS", "").strip()
    if user and password:
        return user, password

    cfg = Path.home() / ".notify-config"
    if cfg.is_file():
        for line in cfg.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("\"'")
            if k == "NOTIFY_SMTP_USER" and not user:
                user = v
            elif k == "NOTIFY_SMTP_PASS" and not password:
                password = v
    return user, password


def send(subject, body, attachment_path=None):
    if os.environ.get("NOTIFY_DISABLE", "").strip() == "1":
        print(f"[notify] DISABLED — would send: {subject}", file=sys.stderr)
        return False

    user, password = _config_loaded()
    to_email = os.environ.get("NOTIFY_TO_EMAIL", "jamesgatsby92@gmail.com")

    if not user or not password:
        print("[notify] NOTIFY_SMTP_USER / NOTIFY_SMTP_PASS not set; "
              "skipping email", file=sys.stderr)
        return False

    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if attachment_path:
        ap = Path(attachment_path)
        if ap.is_file() and ap.stat().st_size < 10 * 1024 * 1024:  # 10MB cap
            with ap.open("rb") as f:
                part = MIMEApplication(f.read(), Name=ap.name)
            part["Content-Disposition"] = f'attachment; filename="{ap.name}"'
            msg.attach(part)
        elif ap.is_file():
            print(f"[notify] log file too large ({ap.stat().st_size} bytes), "
                  f"sending tail only in body", file=sys.stderr)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(user, password)
            server.send_message(msg)
        print(f"[notify] sent: {subject}", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[notify] send failed: {e}", file=sys.stderr)
        return False


def _read_local_config(scraper_dir):
    """Pull DETAIL_HS_CODE / USERNAME / dates from <scraper>/src/config/_local.py
    so the alert can include account context without hard-coding."""
    info = {"hs_code": "?", "username": "?", "start": "?", "end": "?"}
    cfg = Path(scraper_dir) / "src" / "config" / "_local.py"
    if not cfg.is_file():
        return info
    try:
        for line in cfg.read_text().splitlines():
            line = line.strip()
            if line.startswith("USERNAME"):
                info["username"] = line.split("=", 1)[1].strip().strip("\"'")
            elif line.startswith("DETAIL_HS_CODE"):
                info["hs_code"] = line.split("=", 1)[1].strip().strip("\"'")
            elif line.startswith("DETAIL_START_DATE"):
                info["start"] = line.split("=", 1)[1].strip().strip("\"'")
            elif line.startswith("DETAIL_END_DATE"):
                info["end"] = line.split("=", 1)[1].strip().strip("\"'")
    except Exception:
        pass
    return info


def _read_resume_state(scraper_dir):
    """Best-effort — find newest CSV and report row count + last seg/page/stt."""
    state = {"rows": 0, "segment": "?", "page": "?", "stt": "?",
             "csv_path": ""}
    output_dir = Path(scraper_dir) / "output"
    if not output_dir.is_dir():
        return state
    csvs = sorted(output_dir.glob("detail_*.csv"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    if not csvs:
        return state
    csv = csvs[0]
    state["csv_path"] = str(csv)
    try:
        with csv.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        state["rows"] = max(0, len(lines) - 1)
        if len(lines) > 1:
            # CSV columns: segment,page,stt,Declaration No,...
            last = lines[-1].split(",")
            if len(last) >= 3:
                state["segment"] = last[0].strip().strip("\"'")
                state["page"] = last[1].strip().strip("\"'")
                state["stt"] = last[2].strip().strip("\"'")
    except Exception:
        pass
    return state


def _tail(path, n=60):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            block = 8192
            data = b""
            while size > 0 and data.count(b"\n") <= n:
                read_size = min(block, size)
                size -= read_size
                f.seek(size)
                data = f.read(read_size) + data
            return data.decode("utf-8", errors="replace").splitlines()[-n:]
    except Exception:
        return []


def build_failure_email(scraper_dir, log_path, kind, reason):
    """Compose subject + body from the scraper's state + log tail."""
    info = _read_local_config(scraper_dir)
    state = _read_resume_state(scraper_dir)
    hostname = socket.gethostname()
    folder_name = Path(scraper_dir).name

    icon = {"crash": "💀", "hang": "💤", "max_restarts": "🛑",
            "complete": "✅"}.get(kind, "⚠️")
    subject = (f"{icon} [{folder_name}] HS {info['hs_code']} | "
               f"{kind.upper()} | {hostname}")

    log_tail = _tail(log_path, 60) if log_path else []
    body = f"""Scraper alert from {hostname}

═══ Account ═══
Folder    : {folder_name}
Username  : {info['username']}
HS Code   : {info['hs_code']}
Date range: {info['start']} → {info['end']}

═══ Crawl progress ═══
Rows in CSV : {state['rows']:,}
Last scraped: Segment {state['segment']}, Page {state['page']}, STT {state['stt']}
CSV path    : {state['csv_path']}

═══ Failure ═══
Kind  : {kind}
Reason: {reason}
Log   : {log_path}

═══ Last 60 log lines ═══
"""
    body += "\n".join(log_tail) if log_tail else "(no log available)"
    body += "\n\n— end of alert —\n"
    return subject, body


# ─── CLI entry point (used by run_supervised.sh + hang_watcher.sh) ───
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True,
                    choices=["crash", "hang", "max_restarts", "complete"])
    ap.add_argument("--reason", default="")
    ap.add_argument("--scraper-dir", default=".",
                    help="path to the scraper folder (auto-detected if .)")
    ap.add_argument("--log", default="",
                    help="path to current crawl log file")
    args = ap.parse_args()

    scraper_dir = Path(args.scraper_dir).resolve()
    if (scraper_dir / "scripts" / "notify.py").is_file():
        pass  # already at root
    else:
        # Likely we're already in /scripts; bump up one level.
        scraper_dir = scraper_dir.parent
    subject, body = build_failure_email(
        scraper_dir, args.log, args.kind, args.reason)
    ok = send(subject, body, attachment_path=args.log if args.log else None)
    sys.exit(0 if ok else 1)


# ─── Module entry point (used by core_pro_detail.py) ───
def notify_exception(scraper_dir, log_path, exc=None):
    """Call from a Python try/except block. Includes the traceback."""
    if exc is None:
        tb = traceback.format_exc()
    else:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    reason = (str(exc) if exc else "uncaught exception")[:200]
    subject, body = build_failure_email(
        scraper_dir, log_path, "crash", reason)
    body += f"\n\n═══ Python traceback ═══\n{tb}\n"
    return send(subject, body, attachment_path=log_path)


if __name__ == "__main__":
    main()
