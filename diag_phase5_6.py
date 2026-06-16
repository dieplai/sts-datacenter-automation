"""Diagnose robocopy (net use credential issue) and pipeline_watcher timeout."""
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = r"D:\datacenter\scripts"

# ── Phase 5: robocopy with net use ────────────────────────────────────────────
print("=" * 60)
print("Phase 5: Robocopy diagnosis")

# Check if we can reach the server via ping
r = subprocess.run(["ping", "-n", "2", "100.76.219.16"], capture_output=True, text=True, timeout=20)
print(f"ping .16 rc={r.returncode}")
print(r.stdout[-300:])

r2 = subprocess.run(["ping", "-n", "2", "100.76.65.2"], capture_output=True, text=True, timeout=20)
print(f"ping .2 rc={r2.returncode}")
print(r2.stdout[-300:])

# The net use for SMB requires valid Windows credentials on the remote.
# The share was created with FullAccess Everyone — but on Tailscale VPN the
# server may require authentication. We need to establish a session.
# Try net use with username pc and no password (empty)
# BUT net use on Windows blocks on password prompt if wrong — use /PERSISTENT:NO
# and redirect stdin
result_nu = subprocess.run(
    ["net", "use", r"\\100.76.219.16\IPC$", "/user:pc", "", "/PERSISTENT:NO"],
    capture_output=True, text=True, timeout=20,
    input=""
)
print(f"\nnet use IPC$ rc={result_nu.returncode}")
print(f"stdout: {result_nu.stdout[:300]}")
print(f"stderr: {result_nu.stderr[:300]}")

if result_nu.returncode == 0:
    # Now try robocopy
    bronze_dest = r"D:\datacenter\bronze\2026"
    Path(bronze_dest).mkdir(parents=True, exist_ok=True)
    rc_rob = subprocess.run(
        ["robocopy", r"\\100.76.219.16\bronze_16$\acc1", bronze_dest,
         "*.csv", "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/R:1", "/W:2"],
        capture_output=True, text=True, timeout=30
    )
    print(f"\nrobocopy rc={rc_rob.returncode}")
    print(rc_rob.stdout[-600:])
else:
    print("\nCannot authenticate to .16 with empty password. Need PC user password.")
    print("Trying net view to see what auth methods are available...")
    rv = subprocess.run(["net", "view", r"\\100.76.219.16"], capture_output=True, text=True, timeout=15, input="")
    print(f"net view rc={rv.returncode} {rv.stdout[:300]} {rv.stderr[:200]}")

# ── Phase 6: pipeline_watcher ─────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Phase 6: Pipeline watcher diagnosis")

# Import check
result_imp = subprocess.run(
    [sys.executable, "-c",
     f"import sys; sys.path.insert(0, r'{SCRIPTS}'); import pipeline_watcher; print('IMPORT_OK')"],
    capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace"
)
print(f"Import: rc={result_imp.returncode} {result_imp.stdout} {result_imp.stderr[:200]}")

# Check dq_gate.py content
dq_path = Path(SCRIPTS) / "dq_gate.py"
print(f"\ndq_gate.py ({dq_path.stat().st_size} bytes):")
content = dq_path.read_text(encoding="utf-8", errors="replace")
print(content[:1000])

# Run watcher with 45s timeout, watching what it does
print("\nRunning watcher with 45s timeout...")
result_w = subprocess.run(
    [sys.executable, str(Path(SCRIPTS) / "pipeline_watcher.py"),
     "--no-sync", "--once", "--dry-run"],
    capture_output=True, text=True, timeout=45,
    encoding="utf-8", errors="replace",
    cwd=SCRIPTS
)
print(f"watcher rc={result_w.returncode}")
print("STDOUT:")
print(result_w.stdout[:2000])
print("STDERR:")
print(result_w.stderr[:500])

print("\nDone.")
