"""
Comprehensive pipeline test script — all 7 phases.
Run from: D:\Dieplai\sts_pipeline_server\
"""
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import paramiko

# ── Config ────────────────────────────────────────────────────────────────────

SSH_KEY = r"C:\Users\tanmi\.ssh\id_rsa_sts"
SSH_USER = "pc"

ACCOUNTS = [
    {
        "name": "acc1",
        "server": "100.76.219.16",
        "deploy_path": r"C:\CRAWL_STS\Acc1\DEPLOY_ACC_1",
        "email": "vtic.stsgroup@gmail.com",
        "hs": "hs54",
        "type": "Import",
    },
    {
        "name": "acc2",
        "server": "100.76.219.16",
        "deploy_path": r"C:\CRAWL_STS\Acc2\DEPLOY_ACC_2",
        "email": "no.vo@stsgroup.org.vn",
        "hs": "hs55",
        "type": "Import",
    },
    {
        "name": "acc3",
        "server": "100.76.65.2",
        "deploy_path": r"C:\CRAWL_STS\Acc3\DEPLOY_ACC_3",
        "email": "kay.nguyen@stsgroup.org.vn",
        "hs": "hs52",
        "type": "Export",
    },
    {
        "name": "acc4",
        "server": "100.76.65.2",
        "deploy_path": r"C:\CRAWL_STS\Acc4\DEPLOY_ACC_4",
        "email": "nguyenkhanhtailscale@gmail.com",
        "hs": "hs56",
        "type": "Export",
    },
]

PYTHON_EXE = r"C:\Users\PC\AppData\Local\Programs\Python\Python311\python.exe"
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
LOCAL_DRIVER_SETUP = r"D:\Dieplai\sts_pipeline_server\01_crawl_tool\src\driver_setup.py"

SERVERS_JSON_PATH = r"D:\datacenter\config\servers.json"
BRONZE_DIR = r"D:\datacenter\bronze\2026"
SCRIPTS_DIR = r"D:\datacenter\scripts"

report = []

def log(msg):
    print(msg)
    report.append(msg)

def section(title):
    sep = "=" * 70
    log(f"\n{sep}")
    log(f"  {title}")
    log(sep)

def subsection(title):
    log(f"\n--- {title} ---")

# ── SSH helpers ───────────────────────────────────────────────────────────────

_ssh_clients = {}

def get_ssh(server):
    if server not in _ssh_clients:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        key = paramiko.RSAKey.from_private_key_file(SSH_KEY)
        client.connect(server, username=SSH_USER, pkey=key, timeout=30)
        _ssh_clients[server] = client
        log(f"  [SSH] Connected to {server}")
    return _ssh_clients[server]

def ssh_exec(server, cmd, timeout=60):
    client = get_ssh(server)
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    rc = stdout.channel.recv_exit_status()
    return rc, out, err

def sftp_upload(server, local_path, remote_path):
    client = get_ssh(server)
    sftp = client.open_sftp()
    sftp.put(local_path, remote_path)
    sftp.close()
    log(f"  [SFTP] Uploaded {local_path} -> {server}:{remote_path}")

def close_all_ssh():
    for server, client in _ssh_clients.items():
        try:
            client.close()
        except Exception:
            pass

# ── Phase 1: Pre-flight ───────────────────────────────────────────────────────

def phase1_preflight():
    section("PHASE 1: Pre-flight checks on all 4 accounts")
    results = {}

    for acc in ACCOUNTS:
        name = acc["name"]
        server = acc["server"]
        deploy = acc["deploy_path"]
        subsection(f"{name} on {server} — {deploy}")

        checks = {}

        # 1. venv python exists and works
        venv_py = deploy + r"\venv\Scripts\python.exe"
        rc, out, err = ssh_exec(server, f'if exist "{venv_py}" (echo EXISTS) else (echo MISSING)')
        checks["venv_python_exists"] = "EXISTS" in out
        log(f"  venv python: {'OK' if checks['venv_python_exists'] else 'MISSING'}")

        if checks["venv_python_exists"]:
            rc2, out2, err2 = ssh_exec(server, f'"{venv_py}" --version')
            checks["venv_python_version"] = out2 or err2
            log(f"  venv python version: {checks['venv_python_version']}")

        # 2. driver_setup.py
        driver_setup_remote = deploy + r"\src\driver_setup.py"
        rc, out, err = ssh_exec(server, f'if exist "{driver_setup_remote}" (echo EXISTS) else (echo MISSING)')
        checks["driver_setup_exists"] = "EXISTS" in out
        log(f"  driver_setup.py: {'OK' if checks['driver_setup_exists'] else 'MISSING — will upload'}")

        if not checks["driver_setup_exists"]:
            try:
                sftp_upload(server, LOCAL_DRIVER_SETUP, driver_setup_remote.replace("\\", "/"))
                checks["driver_setup_uploaded"] = True
                log(f"  driver_setup.py: UPLOADED")
            except Exception as e:
                checks["driver_setup_uploaded"] = False
                log(f"  driver_setup.py: UPLOAD FAILED — {e}")

        # 3. Import checks
        if checks.get("venv_python_exists"):
            imports_cmd = (
                f'cd /d "{deploy}" && '
                f'"{venv_py}" -c "import selenium; import pandas; import httpx; print(\'imports_ok\')"'
            )
            rc3, out3, err3 = ssh_exec(server, imports_cmd, timeout=30)
            checks["imports_ok"] = "imports_ok" in out3
            log(f"  imports (selenium/pandas/httpx): {'OK' if checks['imports_ok'] else 'FAILED'}")
            if not checks["imports_ok"] and err3:
                log(f"    ERROR: {err3[:300]}")

            # undetected_chromedriver separately (sometimes not installed)
            uc_cmd = (
                f'"{venv_py}" -c "import undetected_chromedriver; print(\'uc_ok\')"'
            )
            rc4, out4, err4 = ssh_exec(server, uc_cmd, timeout=20)
            checks["undetected_chromedriver"] = "uc_ok" in out4
            log(f"  undetected_chromedriver: {'OK' if checks['undetected_chromedriver'] else 'MISSING'}")
            if not checks["undetected_chromedriver"]:
                log(f"    Note: {err4[:200]}")

        # 4. Chrome
        rc, out, err = ssh_exec(server, f'if exist "{CHROME_PATH}" (echo EXISTS) else (echo MISSING)')
        checks["chrome_exists"] = "EXISTS" in out
        log(f"  Chrome: {'OK' if checks['chrome_exists'] else 'MISSING'}")

        # 5-7. Directories
        for dname, dpath_suffix in [("output", r"\output"), ("output\\manifests", r"\output\manifests"), ("logs", r"\logs")]:
            dpath = deploy + dpath_suffix
            rc, out, err = ssh_exec(server, f'if exist "{dpath}" (echo EXISTS) else (echo MISSING)')
            exists = "EXISTS" in out
            if not exists:
                rc2, out2, err2 = ssh_exec(server, f'mkdir "{dpath}"')
                exists_after = rc2 == 0
                log(f"  dir {dname}: CREATED (rc={rc2})")
                checks[f"dir_{dname.replace(chr(92),'_')}"] = exists_after
            else:
                log(f"  dir {dname}: OK")
                checks[f"dir_{dname.replace(chr(92),'_')}"] = True

        # Also verify src\main.py import works
        if checks.get("venv_python_exists"):
            main_cmd = (
                f'cd /d "{deploy}" && '
                f'"{venv_py}" -c "import sys; sys.path.insert(0,\'src\'); from src.main import main; print(\'main_import_ok\')"'
            )
            rc5, out5, err5 = ssh_exec(server, main_cmd, timeout=30)
            checks["main_import"] = "main_import_ok" in out5
            log(f"  src.main import: {'OK' if checks['main_import'] else 'FAILED'}")
            if not checks["main_import"] and err5:
                log(f"    ERROR: {err5[:400]}")

        results[name] = checks

    log("\n[Phase 1 Summary]")
    for name, checks in results.items():
        ok = all(v is True or (isinstance(v, str) and v) for v in checks.values()
                 if isinstance(v, bool))
        log(f"  {name}: {'READY' if ok else 'HAS ISSUES'}")
        for k, v in checks.items():
            log(f"    {k}: {v}")

    return results

# ── Phase 2: SMB shares ───────────────────────────────────────────────────────

def phase2_smb_shares():
    section("PHASE 2: Configure UNC shares (SMB) on crawl servers")

    share_configs = {
        "100.76.219.16": {
            "bronze_share": "C:\\\\bronze_share",
            "bronze_share_name": "bronze_16$",
            "manifests_share": "C:\\\\manifests_share",
            "manifests_share_name": "manifests_16$",
            "accounts": [
                {"name": "acc1", "output": "C:\\\\CRAWL_STS\\\\Acc1\\\\DEPLOY_ACC_1\\\\output", "manifests": "C:\\\\CRAWL_STS\\\\Acc1\\\\DEPLOY_ACC_1\\\\output\\\\manifests"},
                {"name": "acc2", "output": "C:\\\\CRAWL_STS\\\\Acc2\\\\DEPLOY_ACC_2\\\\output", "manifests": "C:\\\\CRAWL_STS\\\\Acc2\\\\DEPLOY_ACC_2\\\\output\\\\manifests"},
            ],
        },
        "100.76.65.2": {
            "bronze_share": "C:\\\\bronze_share",
            "bronze_share_name": "bronze_2$",
            "manifests_share": "C:\\\\manifests_share",
            "manifests_share_name": "manifests_2$",
            "accounts": [
                {"name": "acc3", "output": "C:\\\\CRAWL_STS\\\\Acc3\\\\DEPLOY_ACC_3\\\\output", "manifests": "C:\\\\CRAWL_STS\\\\Acc3\\\\DEPLOY_ACC_3\\\\output\\\\manifests"},
                {"name": "acc4", "output": "C:\\\\CRAWL_STS\\\\Acc4\\\\DEPLOY_ACC_4\\\\output", "manifests": "C:\\\\CRAWL_STS\\\\Acc4\\\\DEPLOY_ACC_4\\\\output\\\\manifests"},
            ],
        },
    }

    results = {}

    for server, cfg in share_configs.items():
        subsection(f"Server {server}")
        server_results = {}

        # Enable SMB server feature and firewall rule
        log(f"  Enabling SMB server service...")
        rc, out, err = ssh_exec(server, 'powershell -Command "Set-Service -Name lanmanserver -StartupType Automatic; Start-Service lanmanserver; Write-Output OK"', timeout=30)
        log(f"  SMB service: rc={rc}, out={out[:100]}")

        # Enable SMB firewall rule
        rc2, out2, err2 = ssh_exec(server, 'powershell -Command "netsh advfirewall firewall set rule group=\'File and Printer Sharing\' new enable=Yes; Write-Output OK"', timeout=20)
        log(f"  Firewall SMB: rc={rc2}")

        # Create bronze_share directory
        bs = cfg["bronze_share"]
        rc3, out3, err3 = ssh_exec(server, f'powershell -Command "New-Item -ItemType Directory -Force -Path \'{bs}\'; Write-Output OK"', timeout=20)
        log(f"  Create {bs}: rc={rc3}")

        # Create manifests_share directory
        ms = cfg["manifests_share"]
        rc4, out4, err4 = ssh_exec(server, f'powershell -Command "New-Item -ItemType Directory -Force -Path \'{ms}\'; Write-Output OK"', timeout=20)
        log(f"  Create {ms}: rc={rc4}")

        # Create junctions for each account
        for acc_cfg in cfg["accounts"]:
            aname = acc_cfg["name"]
            output_src = acc_cfg["output"]
            manifests_src = acc_cfg["manifests"]

            # Ensure source output dir exists
            ssh_exec(server, f'powershell -Command "New-Item -ItemType Directory -Force -Path \'{output_src}\'"', timeout=15)
            ssh_exec(server, f'powershell -Command "New-Item -ItemType Directory -Force -Path \'{manifests_src}\'"', timeout=15)

            # Junction: bronze_share\accN -> DEPLOY\output
            bjunct = bs + "\\\\" + aname
            # Remove if exists first
            ssh_exec(server, f'powershell -Command "if (Test-Path \'{bjunct}\') {{ Remove-Item -Force -Recurse \'{bjunct}\' }}"', timeout=15)
            rc_j, out_j, err_j = ssh_exec(server, f'cmd /c mklink /J "{bjunct.replace(chr(92)*2, chr(92))}" "{output_src.replace(chr(92)*2, chr(92))}"', timeout=15)
            log(f"  Junction bronze/{aname}: rc={rc_j} {out_j[:80] if out_j else ''}{err_j[:80] if err_j else ''}")
            server_results[f"junction_bronze_{aname}"] = rc_j == 0

            # Junction: manifests_share\accN -> DEPLOY\output\manifests
            mjunct = ms + "\\\\" + aname
            ssh_exec(server, f'powershell -Command "if (Test-Path \'{mjunct}\') {{ Remove-Item -Force -Recurse \'{mjunct}\' }}"', timeout=15)
            rc_m, out_m, err_m = ssh_exec(server, f'cmd /c mklink /J "{mjunct.replace(chr(92)*2, chr(92))}" "{manifests_src.replace(chr(92)*2, chr(92))}"', timeout=15)
            log(f"  Junction manifests/{aname}: rc={rc_m} {out_m[:80] if out_m else ''}{err_m[:80] if err_m else ''}")
            server_results[f"junction_manifests_{aname}"] = rc_m == 0

        # Create bronze SMB share
        bname = cfg["bronze_share_name"]
        # Remove existing share if any
        ssh_exec(server, f'powershell -Command "try {{ Remove-SmbShare -Name \'{bname}\' -Force -ErrorAction Stop }} catch {{ }}"', timeout=15)
        rc_s, out_s, err_s = ssh_exec(server,
            f'powershell -Command "New-SmbShare -Name \'{bname}\' -Path \'{bs}\' -FullAccess \'Everyone\'; Write-Output SHARE_OK"',
            timeout=20)
        log(f"  SMB share {bname}: rc={rc_s} out={out_s[:100]}")
        server_results[f"share_{bname}"] = "SHARE_OK" in out_s or rc_s == 0

        # Create manifests SMB share
        mname = cfg["manifests_share_name"]
        ssh_exec(server, f'powershell -Command "try {{ Remove-SmbShare -Name \'{mname}\' -Force -ErrorAction Stop }} catch {{ }}"', timeout=15)
        rc_ms2, out_ms2, err_ms2 = ssh_exec(server,
            f'powershell -Command "New-SmbShare -Name \'{mname}\' -Path \'{ms}\' -FullAccess \'Everyone\'; Write-Output SHARE_OK"',
            timeout=20)
        log(f"  SMB share {mname}: rc={rc_ms2} out={out_ms2[:100]}")
        server_results[f"share_{mname}"] = "SHARE_OK" in out_ms2 or rc_ms2 == 0

        # Verify shares
        rc_v, out_v, err_v = ssh_exec(server, 'powershell -Command "Get-SmbShare | Select-Object Name,Path | ConvertTo-Json"', timeout=20)
        log(f"  Active shares on {server}:")
        log(f"    {out_v[:500]}")

        results[server] = server_results

    log("\n[Phase 2 Summary]")
    for server, sr in results.items():
        for k, v in sr.items():
            status = "OK" if v else "FAILED"
            log(f"  {server} {k}: {status}")

    return results

# ── Phase 3: Update servers.json ──────────────────────────────────────────────

def phase3_update_servers_json():
    section("PHASE 3: Update servers.json")

    new_config = [
        {"name": "CRAWL-16-acc1",
         "unc_bronze": "\\\\100.76.219.16\\bronze_16$\\acc1",
         "unc_manifests": "\\\\100.76.219.16\\manifests_16$\\acc1"},
        {"name": "CRAWL-16-acc2",
         "unc_bronze": "\\\\100.76.219.16\\bronze_16$\\acc2",
         "unc_manifests": "\\\\100.76.219.16\\manifests_16$\\acc2"},
        {"name": "CRAWL-2-acc3",
         "unc_bronze": "\\\\100.76.65.2\\bronze_2$\\acc3",
         "unc_manifests": "\\\\100.76.65.2\\manifests_2$\\acc3"},
        {"name": "CRAWL-2-acc4",
         "unc_bronze": "\\\\100.76.65.2\\bronze_2$\\acc4",
         "unc_manifests": "\\\\100.76.65.2\\manifests_2$\\acc4"},
    ]

    servers_path = Path(SERVERS_JSON_PATH)
    old_content = servers_path.read_text(encoding="utf-8")
    log(f"  Old servers.json:\n{old_content}")

    new_content = json.dumps(new_config, indent=2, ensure_ascii=False)
    servers_path.write_text(new_content, encoding="utf-8")
    log(f"  New servers.json written:\n{new_content}")
    log("  [Phase 3] servers.json UPDATED")
    return True

# ── Phase 4: Import test + quick crawl on acc1 ────────────────────────────────

def phase4_crawl_test():
    section("PHASE 4: Import test + quick 1-page crawl on acc1")
    results = {}

    for acc in ACCOUNTS:
        name = acc["name"]
        server = acc["server"]
        deploy = acc["deploy_path"]
        venv_py = deploy + r"\venv\Scripts\python.exe"

        subsection(f"Import test: {name}")
        # Quick import test
        cmd = (
            f'cd /d "{deploy}" && '
            f'"{venv_py}" -c "import sys; sys.path.insert(0,\'.\'); from src.main import main; print(\'import_ok\')"'
        )
        rc, out, err = ssh_exec(server, cmd, timeout=30)
        ok = "import_ok" in out
        results[f"{name}_import"] = ok
        log(f"  {name} import: {'OK' if ok else 'FAILED'}")
        if not ok:
            log(f"    stdout: {out[:300]}")
            log(f"    stderr: {err[:300]}")

    # Quick crawl test on acc1 only (2 pages, hs59 Import)
    subsection("Quick crawl test: acc1 (2 pages)")
    acc1 = ACCOUNTS[0]
    server = acc1["server"]
    deploy = acc1["deploy_path"]
    venv_py = deploy + r"\venv\Scripts\python.exe"
    local_py = deploy + r"\src\config\_local.py"

    # Read current _local.py
    rc, current_local, err = ssh_exec(server, f'type "{local_py}"')
    log(f"  Current _local.py (first 600 chars):\n  {current_local[:600]}")

    # Kill existing Chrome first
    log("  Killing existing Chrome processes...")
    ssh_exec(server, 'taskkill /F /IM chrome.exe /T 2>nul', timeout=10)
    ssh_exec(server, 'taskkill /F /IM chromedriver.exe /T 2>nul', timeout=10)
    time.sleep(2)

    # Patch _local.py: set DETAIL_MAX_PAGES=2 temporarily and ensure INTERMEDIATE_FORMAT='csv'
    # We'll backup and restore
    backup_cmd = f'copy /Y "{local_py}" "{local_py}.bak"'
    ssh_exec(server, backup_cmd, timeout=10)

    # Patch via PowerShell: replace DETAIL_MAX_PAGES line
    patch_cmd = (
        f'powershell -Command "'
        f'$f = Get-Content \'{local_py}\' -Raw; '
        f'$f = $f -replace \'DETAIL_MAX_PAGES\\s*=\\s*None\', \'DETAIL_MAX_PAGES = 2\'; '
        f'$f = $f -replace \'DETAIL_MAX_PAGES\\s*=\\s*\\d+\', \'DETAIL_MAX_PAGES = 2\'; '
        f'Set-Content \'{local_py}\' $f -Encoding UTF8; '
        f'Write-Output PATCHED'
        f'"'
    )
    rc_p, out_p, err_p = ssh_exec(server, patch_cmd, timeout=15)
    log(f"  Patch DETAIL_MAX_PAGES=2: {out_p[:100]} rc={rc_p}")

    # Run crawl with timeout (5 minutes max for a quick test)
    log("  Starting crawl (timeout=5min)...")
    crawl_cmd = (
        f'cd /d "{deploy}" && '
        f'"{venv_py}" -m src.main 2>&1'
    )
    rc_c, out_c, err_c = ssh_exec(server, crawl_cmd, timeout=300)
    log(f"  Crawl rc={rc_c}")
    log(f"  Crawl output (last 1000 chars):\n{out_c[-1000:] if out_c else ''}")
    if err_c:
        log(f"  Crawl stderr:\n{err_c[-500:]}")

    results["acc1_crawl_rc"] = rc_c
    results["acc1_crawl_output"] = out_c[-500:]

    # Restore _local.py
    restore_cmd = f'copy /Y "{local_py}.bak" "{local_py}"'
    rc_r, out_r, err_r = ssh_exec(server, restore_cmd, timeout=10)
    log(f"  Restored _local.py: rc={rc_r}")

    # Check for output CSVs
    output_dir = deploy + r"\output"
    rc_ls, out_ls, err_ls = ssh_exec(server, f'dir /B "{output_dir}\\*.csv" 2>nul', timeout=10)
    csv_files = [f.strip() for f in out_ls.splitlines() if f.strip().endswith(".csv")]
    results["acc1_csv_files"] = csv_files
    log(f"  CSVs in output: {csv_files}")

    # Check row counts
    for csv_file in csv_files[:3]:  # first 3
        csv_path = output_dir + "\\" + csv_file
        rc_wc, out_wc, err_wc = ssh_exec(server,
            f'powershell -Command "(Import-Csv \'{csv_path}\').Count"',
            timeout=20)
        log(f"  {csv_file}: ~{out_wc.strip()} rows")
        results[f"rows_{csv_file}"] = out_wc.strip()

    log("\n[Phase 4 Summary]")
    for k, v in results.items():
        if not k.endswith("_output"):
            log(f"  {k}: {v}")

    return results

# ── Phase 5: Robocopy pull test ────────────────────────────────────────────────

def phase5_robocopy():
    section("PHASE 5: Robocopy pull from Server .16 to storage")
    results = {}

    unc_src = r"\\100.76.219.16\bronze_16$\acc1"
    dest = BRONZE_DIR
    Path(dest).mkdir(parents=True, exist_ok=True)

    cmd = [
        "robocopy", unc_src, dest,
        "*.csv", "/E", "/NFL", "/NDL", "/NJH", "/NJS",
        "/R:2", "/W:5",
    ]
    log(f"  Command: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        log(f"  robocopy rc={result.returncode}")
        log(f"  stdout: {result.stdout[-800:]}")
        if result.stderr:
            log(f"  stderr: {result.stderr[-400:]}")
        # robocopy rc 0=no files, 1=ok copied, 2=extra, 3=both, >=8=error
        ok = result.returncode < 8
        results["robocopy_ok"] = ok
        results["robocopy_rc"] = result.returncode

        # Count files in dest
        files = list(Path(dest).glob("*.csv"))
        results["files_in_bronze"] = [f.name for f in files]
        log(f"  Files in {dest}: {[f.name for f in files]}")
    except subprocess.TimeoutExpired:
        log("  robocopy TIMED OUT — share may not be accessible")
        results["robocopy_ok"] = False
        results["robocopy_error"] = "timeout"
    except Exception as e:
        log(f"  robocopy FAILED: {e}")
        results["robocopy_ok"] = False
        results["robocopy_error"] = str(e)

    return results

# ── Phase 6: Pipeline watcher dry-run ─────────────────────────────────────────

def phase6_pipeline_watcher():
    section("PHASE 6: Pipeline watcher --no-sync --once --dry-run")
    results = {}

    # First check psycopg2 available
    try:
        import psycopg2
        log("  psycopg2: available")
    except ImportError:
        log("  psycopg2: NOT installed — pipeline_watcher will fail")
        results["psycopg2"] = False
        return results

    results["psycopg2"] = True

    # Check if dq_gate.py exists
    dq_gate = Path(SCRIPTS_DIR) / "dq_gate.py"
    results["dq_gate_exists"] = dq_gate.exists()
    log(f"  dq_gate.py: {'exists' if dq_gate.exists() else 'MISSING'}")

    # Check 04_load_staging.py
    load_staging = Path(SCRIPTS_DIR) / "04_load_staging.py"
    results["load_staging_exists"] = load_staging.exists()
    log(f"  04_load_staging.py: {'exists' if load_staging.exists() else 'MISSING'}")

    # Run dry-run
    cmd = [sys.executable, str(Path(SCRIPTS_DIR) / "pipeline_watcher.py"),
           "--no-sync", "--once", "--dry-run"]
    log(f"  Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace"
        )
        log(f"  rc={result.returncode}")
        log(f"  stdout:\n{result.stdout[-1500:]}")
        if result.stderr:
            log(f"  stderr:\n{result.stderr[-600:]}")
        results["watcher_rc"] = result.returncode
        results["watcher_ok"] = result.returncode == 0
    except subprocess.TimeoutExpired:
        log("  pipeline_watcher TIMED OUT")
        results["watcher_ok"] = False
        results["watcher_error"] = "timeout"
    except Exception as e:
        log(f"  pipeline_watcher FAILED: {e}")
        results["watcher_ok"] = False
        results["watcher_error"] = str(e)

    return results

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    section("STS Pipeline — Comprehensive Test Run")
    log(f"Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    all_results = {}

    try:
        all_results["phase1"] = phase1_preflight()
    except Exception as e:
        import traceback
        log(f"\n[Phase 1 CRASH] {e}\n{traceback.format_exc()}")
        all_results["phase1"] = {"error": str(e)}

    try:
        all_results["phase2"] = phase2_smb_shares()
    except Exception as e:
        import traceback
        log(f"\n[Phase 2 CRASH] {e}\n{traceback.format_exc()}")
        all_results["phase2"] = {"error": str(e)}

    try:
        all_results["phase3"] = phase3_update_servers_json()
    except Exception as e:
        import traceback
        log(f"\n[Phase 3 CRASH] {e}\n{traceback.format_exc()}")
        all_results["phase3"] = {"error": str(e)}

    try:
        all_results["phase4"] = phase4_crawl_test()
    except Exception as e:
        import traceback
        log(f"\n[Phase 4 CRASH] {e}\n{traceback.format_exc()}")
        all_results["phase4"] = {"error": str(e)}

    try:
        all_results["phase5"] = phase5_robocopy()
    except Exception as e:
        import traceback
        log(f"\n[Phase 5 CRASH] {e}\n{traceback.format_exc()}")
        all_results["phase5"] = {"error": str(e)}

    try:
        all_results["phase6"] = phase6_pipeline_watcher()
    except Exception as e:
        import traceback
        log(f"\n[Phase 6 CRASH] {e}\n{traceback.format_exc()}")
        all_results["phase6"] = {"error": str(e)}

    close_all_ssh()

    # Save full report
    report_path = Path(r"D:\Dieplai\sts_pipeline_server\pipeline_test_report.txt")
    report_path.write_text("\n".join(report), encoding="utf-8")
    log(f"\nFull report saved to: {report_path}")

    section("PHASE 7: FINAL SUMMARY")
    log(f"Completed at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
