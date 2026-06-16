"""
Fix SMB blank password restriction on crawl servers.
Windows by default blocks network logins with blank passwords via a local policy.
We need to either:
1. Set a password for PC user on the crawl servers, OR
2. Disable the "Accounts: Limit local account use of blank passwords" policy
"""
import paramiko
import subprocess
from pathlib import Path

SSH_KEY = r"C:\Users\tanmi\.ssh\id_rsa_sts"
SSH_USER = "pc"

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

for server in ["100.76.219.16", "100.76.65.2"]:
    print(f"\n{'='*60}")
    print(f"Fixing SMB blank password policy on {server}")
    c = get_ssh(server)

    # Check current policy
    rc0, o0, e0 = run(c,
        'powershell -ExecutionPolicy Bypass -Command "'
        'secedit /export /cfg C:\\temp_secpol.cfg /areas SECURITYPOLICY; '
        'if (!(Test-Path C:\\temp_secpol.cfg)) { New-Item -ItemType Directory -Force -Path C:\\temp_secpol.cfg }; '
        'Write-Output EXPORTED'
        '"', timeout=20)
    print(f"  secedit export: {o0[:100]} rc={rc0}")

    # The key registry value to disable blank password restriction:
    # HKLM\SYSTEM\CurrentControlSet\Control\Lsa - LimitBlankPasswordUse = 0
    rc1, o1, e1 = run(c,
        'powershell -ExecutionPolicy Bypass -Command "'
        '$val = Get-ItemPropertyValue HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Lsa -Name LimitBlankPasswordUse; '
        'Write-Output $val'
        '"', timeout=15)
    print(f"  LimitBlankPasswordUse current value: {o1}")

    # Set it to 0 to allow blank password network logins
    rc2, o2, e2 = run(c,
        'powershell -ExecutionPolicy Bypass -Command "'
        'Set-ItemProperty HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Lsa -Name LimitBlankPasswordUse -Value 0; '
        '$newval = Get-ItemPropertyValue HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Lsa -Name LimitBlankPasswordUse; '
        'Write-Output $newval'
        '"', timeout=15)
    print(f"  Set LimitBlankPasswordUse=0: new value={o2} rc={rc2}")
    if e2:
        print(f"  Error: {e2[:200]}")

    # Verify
    rc3, o3, e3 = run(c,
        'powershell -ExecutionPolicy Bypass -Command "'
        'Get-ItemPropertyValue HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Lsa -Name LimitBlankPasswordUse'
        '"', timeout=10)
    print(f"  Verified LimitBlankPasswordUse: {o3}")

    c.close()

# Now test robocopy again
print(f"\n{'='*60}")
print("Testing robocopy after policy fix")
import time
time.sleep(2)  # give policy a moment

# net use
result_nu = subprocess.run(
    ["net", "use", r"\\100.76.219.16\IPC$", "/user:pc", "", "/PERSISTENT:NO"],
    capture_output=True, text=True, timeout=20,
    input=""
)
print(f"net use IPC$ rc={result_nu.returncode}: {result_nu.stdout[:200]} {result_nu.stderr[:200]}")

if result_nu.returncode == 0:
    # Try robocopy
    dest = r"D:\datacenter\bronze\2026"
    Path(dest).mkdir(parents=True, exist_ok=True)
    rc_rob = subprocess.run(
        ["robocopy", r"\\100.76.219.16\bronze_16$\acc1", dest,
         "*.csv", "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/R:1", "/W:2"],
        capture_output=True, text=True, timeout=30
    )
    print(f"robocopy rc={rc_rob.returncode}")
    print(rc_rob.stdout[-500:] if rc_rob.stdout else "")

    # Clean up net use
    subprocess.run(["net", "use", r"\\100.76.219.16\IPC$", "/delete"],
                   capture_output=True, text=True, timeout=10)
else:
    print("net use still failing — SMB authentication requires a non-blank password")
    print("MANUAL ACTION REQUIRED: Set a password for the PC user on crawl servers,")
    print("then add it to sync_servers.py via 'net use' or Windows Credential Manager.")

print("\nDone.")
