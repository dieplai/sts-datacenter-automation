"""
Fix SMB shares (execution policy issue) and verify crawl output.
"""
import json
import paramiko
import subprocess
import time
from pathlib import Path

SSH_KEY = r"C:\Users\tanmi\.ssh\id_rsa_sts"
SSH_USER = "pc"

def get_ssh(server):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    key = paramiko.RSAKey.from_private_key_file(SSH_KEY)
    client.connect(server, username=SSH_USER, pkey=key, timeout=15)
    return client

def run(client, cmd, timeout=30):
    _, out, err = client.exec_command(cmd, timeout=timeout)
    o = out.read().decode("utf-8", errors="replace").strip()
    e = err.read().decode("utf-8", errors="replace").strip()
    rc = out.channel.recv_exit_status()
    return rc, o, e

def fix_smb(server, bronze_name, manifests_name):
    print(f"\n{'='*60}")
    print(f"Fixing SMB shares on {server}")
    c = get_ssh(server)

    # Set execution policy to bypass for PowerShell
    rc0, o0, e0 = run(c, 'powershell -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope LocalMachine -Force; Write-Output EP_SET"')
    print(f"  ExecutionPolicy set: {o0[:100]} rc={rc0}")

    # Now create the shares using -ExecutionPolicy Bypass
    bronze_path = "C:\\bronze_share"
    manifests_path = "C:\\manifests_share"

    # Verify dirs exist
    rc1, o1, _ = run(c, f'if exist "{bronze_path}" (echo EXISTS) else (echo MISSING)')
    print(f"  bronze_share dir: {o1}")
    rc2, o2, _ = run(c, f'if exist "{manifests_path}" (echo EXISTS) else (echo MISSING)')
    print(f"  manifests_share dir: {o2}")

    # Create shares with ExecutionPolicy Bypass
    for share_name, path in [(bronze_name, bronze_path), (manifests_name, manifests_path)]:
        # Remove existing
        cmd_remove = f'powershell -ExecutionPolicy Bypass -Command "Remove-SmbShare -Name \'{share_name}\' -Force -ErrorAction SilentlyContinue"'
        run(c, cmd_remove, timeout=15)
        time.sleep(1)

        # Create
        cmd_create = (
            f'powershell -ExecutionPolicy Bypass -Command "'
            f'New-SmbShare -Name \'{share_name}\' -Path \'{path}\' -FullAccess \'Everyone\' -ErrorAction Stop; '
            f'Write-Output SHARE_CREATED'
            f'"'
        )
        rc_s, out_s, err_s = run(c, cmd_create, timeout=20)
        print(f"  Create {share_name}: rc={rc_s} out={out_s[:150]} err={err_s[:100] if err_s else ''}")

    # Verify with net share
    rc_v, out_v, _ = run(c, "net share")
    print(f"  net share output:\n{out_v}")

    c.close()

def verify_crawl_csv(server, deploy):
    """Check if acc1 crawl produced any CSVs."""
    print(f"\n{'='*60}")
    print(f"Verifying crawl output on {server}:{deploy}")
    c = get_ssh(server)

    output_dir = deploy + r"\output"
    rc, out, err = run(c, f'dir /B /S "{output_dir}\\*.csv" 2>nul')
    print(f"  CSV files: {out[:500] if out else 'NONE'}")

    if out:
        csv_files = [f.strip() for f in out.splitlines() if f.strip().endswith(".csv")]
        for csv_path in csv_files[:3]:
            # Count rows
            rc2, out2, err2 = run(c,
                f'powershell -ExecutionPolicy Bypass -Command "(Import-Csv \'{csv_path}\').Count"',
                timeout=20)
            print(f"  {csv_path}: {out2.strip()} rows")
        return csv_files
    else:
        # Check logs for what went wrong
        logs_dir = deploy + r"\logs"
        rc3, out3, _ = run(c, f'dir /B "{logs_dir}" 2>nul')
        print(f"  Log files: {out3[:300]}")
        if out3:
            for log_file in out3.splitlines()[:2]:
                log_path = logs_dir + "\\" + log_file.strip()
                rc4, out4, _ = run(c, f'type "{log_path}" 2>nul')
                print(f"  --- {log_file} (last 500) ---")
                print(out4[-500:] if out4 else "EMPTY")

        # Also check the main.py to understand what it does
        rc5, o5, _ = run(c, f'type "{deploy}\\src\\main.py"')
        print(f"\n  main.py content:\n{o5}")

    c.close()
    return []

def test_crawl_verbose(server, deploy):
    """Run crawl with explicit UTF-8 output and capture full output."""
    print(f"\n{'='*60}")
    print(f"Running crawl test (verbose) on {server}:{deploy}")
    c = get_ssh(server)

    venv_py = deploy + r"\venv\Scripts\python.exe"

    # First check if DETAIL_MAX_PAGES is set correctly
    local_py = deploy + r"\src\config\_local.py"
    rc0, out0, _ = run(c, f'findstr "DETAIL_MAX_PAGES" "{local_py}"')
    print(f"  DETAIL_MAX_PAGES in _local.py: {out0}")

    # Patch it to 2 pages
    patch = (
        f'powershell -ExecutionPolicy Bypass -Command "'
        f'$f = Get-Content \'{local_py}\' -Raw; '
        f'$f = $f -replace \'DETAIL_MAX_PAGES\\\\s*=\\\\s*None\', \'DETAIL_MAX_PAGES = 2\'; '
        f'$f = $f -replace \'DETAIL_MAX_PAGES\\\\s*=\\\\s*\\\\d+\', \'DETAIL_MAX_PAGES = 2\'; '
        f'Set-Content \'{local_py}\' $f -Encoding UTF8; '
        f'Write-Output PATCHED'
        f'"'
    )
    rc_p, out_p, _ = run(c, patch, timeout=10)
    print(f"  Patch DETAIL_MAX_PAGES=2: {out_p}")

    # Backup
    run(c, f'copy /Y "{local_py}" "{local_py}.bak"', timeout=5)

    # Kill chrome
    run(c, "taskkill /F /IM chrome.exe /T 2>nul", timeout=5)
    run(c, "taskkill /F /IM chromedriver.exe /T 2>nul", timeout=5)
    time.sleep(2)

    # Run with PYTHONIOENCODING=utf-8
    cmd = (
        f'cd /d "{deploy}" && '
        f'set PYTHONIOENCODING=utf-8 && '
        f'"{venv_py}" -m src.main 2>&1'
    )
    print("  Starting crawl (3 min timeout)...")
    rc_c, out_c, err_c = run(c, cmd, timeout=180)
    print(f"  Crawl rc={rc_c}")
    print(f"  Output (last 2000):\n{out_c[-2000:] if out_c else 'EMPTY'}")
    if err_c:
        print(f"  Stderr (last 500):\n{err_c[-500:]}")

    # Restore
    run(c, f'copy /Y "{local_py}.bak" "{local_py}"', timeout=5)

    # Check for CSVs
    output_dir = deploy + r"\output"
    rc_ls, out_ls, _ = run(c, f'dir /B /S "{output_dir}\\*.csv" 2>nul', timeout=10)
    csv_files = [f.strip() for f in out_ls.splitlines() if f.strip().endswith(".csv")] if out_ls else []
    print(f"  CSVs produced: {csv_files}")
    for csv_path in csv_files[:3]:
        rc_cnt, out_cnt, _ = run(c,
            f'powershell -ExecutionPolicy Bypass -Command "(Import-Csv \'{csv_path}\').Count"',
            timeout=20)
        print(f"    {csv_path}: {out_cnt.strip()} rows")

    c.close()
    return rc_c, csv_files, out_c

def test_robocopy_with_creds():
    """Test robocopy with explicit credentials."""
    print(f"\n{'='*60}")
    print("Testing robocopy with net use credentials")

    # Try connecting with SMB using PC user credentials
    # First check if the share is reachable via net use
    result = subprocess.run(
        ["net", "use", r"\\100.76.219.16\bronze_16$", "/user:pc", ""],
        capture_output=True, text=True, timeout=15
    )
    print(f"  net use (no password): rc={result.returncode} {result.stdout[:200]} {result.stderr[:200]}")

    # Try with IPC$
    result2 = subprocess.run(
        ["net", "view", r"\\100.76.219.16"],
        capture_output=True, text=True, timeout=15
    )
    print(f"  net view .16: rc={result2.returncode}")
    print(f"  stdout: {result2.stdout[:300]}")
    print(f"  stderr: {result2.stderr[:300]}")

    # Check if this machine can reach the share at all
    result3 = subprocess.run(
        ["ping", "-n", "2", "100.76.219.16"],
        capture_output=True, text=True, timeout=15
    )
    print(f"  ping .16: rc={result3.returncode}")
    print(f"  {result3.stdout[-200:]}")

def check_pipeline_watcher_timeout():
    """See what's blocking pipeline_watcher."""
    print(f"\n{'='*60}")
    print("Diagnosing pipeline_watcher timeout")
    scripts = Path(r"D:\datacenter\scripts")

    # Check if dq_gate.py has issues
    dq_gate = scripts / "dq_gate.py"
    if dq_gate.exists():
        content = dq_gate.read_text(encoding="utf-8", errors="replace")
        print(f"  dq_gate.py ({len(content)} chars), first 500:")
        print(content[:500])

    # Check sync_servers.py
    sync = scripts / "sync_servers.py"
    if sync.exists():
        content2 = sync.read_text(encoding="utf-8", errors="replace")
        print(f"\n  sync_servers.py ({len(content2)} chars), first 500:")
        print(content2[:500])

    # Try importing pipeline_watcher standalone
    result = subprocess.run(
        ["python", "-c",
         "import sys; sys.path.insert(0, r'D:\\datacenter\\scripts'); "
         "import pipeline_watcher; print('import OK')"],
        capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace"
    )
    print(f"\n  Import pipeline_watcher: rc={result.returncode}")
    print(f"  stdout: {result.stdout}")
    print(f"  stderr: {result.stderr[:300]}")

    # Run with short timeout just to see where it hangs
    result2 = subprocess.run(
        ["python", r"D:\datacenter\scripts\pipeline_watcher.py",
         "--no-sync", "--once", "--dry-run"],
        capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
        cwd=r"D:\datacenter\scripts"
    )
    print(f"\n  pipeline_watcher 30s run: rc={result2.returncode}")
    print(f"  stdout: {result2.stdout[:1500]}")
    print(f"  stderr: {result2.stderr[:500]}")

if __name__ == "__main__":
    # Fix SMB shares with proper execution policy
    fix_smb("100.76.219.16", "bronze_16$", "manifests_16$")
    fix_smb("100.76.65.2", "bronze_2$", "manifests_2$")

    # Verify crawl CSVs from Phase 4
    verify_crawl_csv("100.76.219.16", r"C:\CRAWL_STS\Acc1\DEPLOY_ACC_1")

    # Run a verbose crawl test on acc1
    rc, csvs, output = test_crawl_verbose("100.76.219.16", r"C:\CRAWL_STS\Acc1\DEPLOY_ACC_1")

    # Test robocopy
    test_robocopy_with_creds()

    # Diagnose pipeline_watcher
    check_pipeline_watcher_timeout()

    print("\nDone.")
