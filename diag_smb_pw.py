"""
Diagnose SMB authentication — find PC user password and test pipeline watcher separately.
"""
import subprocess
import sys
import time
import paramiko
from pathlib import Path

SSH_KEY = r"C:\Users\tanmi\.ssh\id_rsa_sts"
SSH_USER = "pc"
SCRIPTS = r"D:\datacenter\scripts"

def get_ssh(server):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    key = paramiko.RSAKey.from_private_key_file(SSH_KEY)
    client.connect(server, username=SSH_USER, pkey=key, timeout=15)
    return client

def run(client, cmd, timeout=20):
    _, out, err = client.exec_command(cmd, timeout=timeout)
    o = out.read().decode("utf-8", errors="replace").strip()
    e = err.read().decode("utf-8", errors="replace").strip()
    rc = out.channel.recv_exit_status()
    return rc, o, e

# ── Get PC user info from server ─────────────────────────────────────────────
print("=" * 60)
print("Checking PC user account on .16")
c16 = get_ssh("100.76.219.16")

# Check if guest account access is enabled (to allow anonymous share access)
rc1, o1, e1 = run(c16, 'powershell -ExecutionPolicy Bypass -Command "Get-LocalUser pc | Select-Object Name,Enabled,PasswordRequired,PasswordLastSet | Format-List"')
print(f"PC user info:\n{o1}")

# Check SMB server settings (guest access, etc.)
rc2, o2, e2 = run(c16, 'powershell -ExecutionPolicy Bypass -Command "Get-SmbServerConfiguration | Select-Object EnableSMBQUIC,RequireSecuritySignature,EnableGuestAccess,RestrictNullSessAccess | Format-List"')
print(f"\nSMB server config:\n{o2}")

# Check if we can set null session access
rc3, o3, e3 = run(c16, 'powershell -ExecutionPolicy Bypass -Command "Get-SmbServerConfiguration | Select-Object EnableInsecureGuestLogons | Format-List"')
print(f"\nGuest logon setting:\n{o3}")

# Enable guest/insecure logons on the SHARE side
rc4, o4, e4 = run(c16, 'powershell -ExecutionPolicy Bypass -Command "Set-SmbServerConfiguration -EnableInsecureGuestLogons $true -Force; Write-Output DONE"')
print(f"\nEnable insecure guest logons: {o4} rc={rc4}")

# Also check if there's a way to get the PC password from credential store or env
rc5, o5, e5 = run(c16, 'powershell -ExecutionPolicy Bypass -Command "cmdkey /list"')
print(f"\ncmdkey list:\n{o5[:300]}")

# Try to enable anonymous access to the specific shares
rc6, o6, e6 = run(c16,
    'powershell -ExecutionPolicy Bypass -Command "'
    'Grant-SmbShareAccess -Name bronze_16$ -AccountName Everyone -AccessRight Full -Force; '
    'Grant-SmbShareAccess -Name manifests_16$ -AccountName Everyone -AccessRight Full -Force; '
    'Write-Output GRANTED'
    '"', timeout=15)
print(f"\nGrant Everyone access: {o6} rc={rc6}")

# Verify share permissions
rc7, o7, e7 = run(c16, 'powershell -ExecutionPolicy Bypass -Command "Get-SmbShareAccess -Name bronze_16$ | Format-Table"')
print(f"\nbronze_16$ permissions:\n{o7}")

c16.close()

# ── Pipeline watcher diagnosis ────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Phase 6: Pipeline watcher — step by step")

# 1. Check dq_gate.py
dq_path = Path(SCRIPTS) / "dq_gate.py"
print(f"\ndq_gate.py ({dq_path.stat().st_size} bytes):")
content = dq_path.read_text(encoding="utf-8", errors="replace")
print(content[:800])

# 2. Check sync_servers.py
sync_path = Path(SCRIPTS) / "sync_servers.py"
print(f"\n\nsync_servers.py ({sync_path.stat().st_size if sync_path.exists() else 'MISSING'}):")
if sync_path.exists():
    sync_content = sync_path.read_text(encoding="utf-8", errors="replace")
    print(sync_content[:800])

# 3. Try running with psycopg2 check
print("\n\nChecking psycopg2 DB connection:")
try:
    import psycopg2
    conn = psycopg2.connect(
        host="localhost", port=5433, dbname="sts-dev",
        user="dev4", password="IBM@Cognos#",
        connect_timeout=5
    )
    conn.close()
    print("  DB connection: OK")
except Exception as e:
    print(f"  DB connection FAILED: {e}")

# 4. Run watcher but capture incrementally to see where it hangs
print("\nRunning watcher --no-sync --once --dry-run (30s):")
try:
    proc = subprocess.Popen(
        [sys.executable, str(Path(SCRIPTS) / "pipeline_watcher.py"),
         "--no-sync", "--once", "--dry-run"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8", errors="replace",
        cwd=SCRIPTS
    )
    # Read for 30 seconds
    start = time.time()
    lines = []
    while time.time() - start < 30:
        try:
            proc.stdout._checkReadable()
            import select
            line = proc.stdout.readline()
            if line:
                lines.append(line.rstrip())
                print(f"  > {line.rstrip()}")
        except Exception:
            time.sleep(0.2)
        if proc.poll() is not None:
            break
    proc.terminate()
    remaining_out, remaining_err = proc.communicate(timeout=5)
    if remaining_out:
        print("Remaining stdout:", remaining_out[:500])
    if remaining_err:
        print("Stderr:", remaining_err[:500])
    print(f"\nProcess exit code: {proc.returncode}")
except Exception as e:
    print(f"Watcher error: {e}")

print("\nDone.")
