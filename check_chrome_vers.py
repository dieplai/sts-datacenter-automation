import paramiko, sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

def get_ssh(server):
    key = paramiko.RSAKey.from_private_key_file(r'C:\Users\tanmi\.ssh\id_rsa_sts')
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(server, username='pc', pkey=key, timeout=15)
    return c

def run(c, cmd, timeout=20):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    o = out.read().decode('utf-8', errors='replace').strip()
    e = err.read().decode('utf-8', errors='replace').strip()
    rc = out.channel.recv_exit_status()
    return rc, o, e

# Check Chrome on acc1 (version)
c16 = get_ssh('100.76.219.16')

# Read chrome version from registry or file
rc1, o1, e1 = run(c16, r'powershell -ExecutionPolicy Bypass -Command "(Get-Item \"C:\Program Files\Google\Chrome\Application\chrome.exe\").VersionInfo.FileVersion"', timeout=15)
print(f"Chrome version .16: {o1}")

# Check if undetected_chromedriver was patched to handle newer chrome
rc2, o2, e2 = run(c16, r'C:\CRAWL_STS\Acc1\DEPLOY_ACC_1\venv\Scripts\python.exe -c "import undetected_chromedriver; print(undetected_chromedriver.__version__)"', timeout=20)
print(f"uc version acc1: {o2} {e2[:100] if e2 else ''}")

# Check browser.py to understand current driver config
rc3, o3, e3 = run(c16, r'type "C:\CRAWL_STS\Acc1\DEPLOY_ACC_1\src\core\browser.py"', timeout=10)
print(f"\nbrowser.py:\n{o3[:2000]}")

# Check if Chrome is running as a service or background process
rc4, o4, e4 = run(c16, r'tasklist | findstr chrome', timeout=10)
print(f"\nChrome processes:\n{o4[:400]}")

# Check DISPLAY / headless settings in _local.py or browser.py
rc5, o5, e5 = run(c16, r'findstr /i "headless no_sandbox disable_gpu" "C:\CRAWL_STS\Acc1\DEPLOY_ACC_1\src\core\browser.py"', timeout=10)
print(f"\nChrome flags in browser.py:\n{o5}")

# Check if there's a chromedriver in the venv or if undetected_chromedriver downloads it
rc6, o6, e6 = run(c16, r'dir /B "C:\CRAWL_STS\Acc1\DEPLOY_ACC_1\venv\Scripts\chromedriver*" 2>nul', timeout=10)
print(f"\nchromedriver in venv: {o6 if o6 else 'NONE'}")

# Check uc cache
rc7, o7, e7 = run(c16, r'dir /B "C:\Users\PC\AppData\Roaming\undetected_chromedriver" 2>nul', timeout=10)
print(f"uc chromedriver cache: {o7[:200] if o7 else 'NONE'}")

c16.close()
print("\nDone.")
