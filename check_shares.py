"""Check SMB shares and fix issues found in the main test run."""
import paramiko
import time

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

print("=" * 60)
print("Checking SMB shares on .16")
c16 = get_ssh("100.76.219.16")
rc, o, e = run(c16, "net share")
print("net share .16:")
print(o)
print("---")
rc2, o2, e2 = run(c16, "powershell -Command \"Get-SmbShare | Select-Object Name,Path | Format-Table -AutoSize\"")
print("Get-SmbShare .16:")
print(o2)
print("ERR:", e2[:200] if e2 else "")

print("\n" + "=" * 60)
print("Checking SMB shares on .2")
c2 = get_ssh("100.76.65.2")
rc3, o3, e3 = run(c2, "net share")
print("net share .2:")
print(o3)
rc4, o4, e4 = run(c2, "powershell -Command \"Get-SmbShare | Select-Object Name,Path | Format-Table -AutoSize\"")
print("Get-SmbShare .2:")
print(o4)
print("ERR:", e4[:200] if e4 else "")

print("\n" + "=" * 60)
print("Investigating crawl error (UnicodeEncodeError in logger.py)")
# The issue: cp1252 console encoding can't handle Unicode emoji (❌ = ❌)
# Let's check the logger.py on the remote
rc5, o5, e5 = run(c16, r'type "C:\CRAWL_STS\Acc1\DEPLOY_ACC_1\src\observability\logger.py"')
print("logger.py:")
print(o5[:1500])

print("\n" + "=" * 60)
print("Checking actual crawl error beyond UnicodeEncodeError")
# The UnicodeEncodeError is just a print issue — actual error is earlier. Read more of traceback
rc6, o6, e6 = run(c16,
    r'cd /d "C:\CRAWL_STS\Acc1\DEPLOY_ACC_1" && '
    r'"C:\CRAWL_STS\Acc1\DEPLOY_ACC_1\venv\Scripts\python.exe" -W ignore -c '
    r'"import sys; sys.stdout.reconfigure(encoding=\"utf-8\", errors=\"replace\"); '
    r'sys.stderr.reconfigure(encoding=\"utf-8\", errors=\"replace\"); '
    r'from src.main import main; main()" 2>&1',
    timeout=120)
print(f"Quick crawl rc={rc6}")
print("Output (first 3000):")
print(o6[:3000])
if e6:
    print("Stderr:", e6[:1000])

# Also check what the actual exception is (before it hits the print)
rc7, o7, e7 = run(c16,
    r'cd /d "C:\CRAWL_STS\Acc1\DEPLOY_ACC_1" && '
    r'"C:\CRAWL_STS\Acc1\DEPLOY_ACC_1\venv\Scripts\python.exe" -c '
    r'"import sys, io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding=\"utf-8\", errors=\"replace\"); '
    r'sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding=\"utf-8\", errors=\"replace\")" 2>&1',
    timeout=15)
print("Encoding patch test rc=", rc7)

c16.close()
c2.close()
