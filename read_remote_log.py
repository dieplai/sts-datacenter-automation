import paramiko, sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

key = paramiko.RSAKey.from_private_key_file(r'C:\Users\tanmi\.ssh\id_rsa_sts')
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('100.76.219.16', username='pc', pkey=key, timeout=15)

_, out, err = c.exec_command(r'type C:\CRAWL_STS\Acc1\DEPLOY_ACC_1\logs\run.log', timeout=10)
o = out.read().decode('utf-8', errors='replace')
print('LAST 3000 CHARS OF run.log:')
print(o[-3000:])

# Also check the _local.py to see if DETAIL_MAX_PAGES was restored
_, out2, err2 = c.exec_command(r'findstr /n "" "C:\CRAWL_STS\Acc1\DEPLOY_ACC_1\src\config\_local.py"', timeout=10)
o2 = out2.read().decode('utf-8', errors='replace')
print('\n_local.py:')
print(o2[:1500])

# Check Chrome version
_, out3, _ = c.exec_command(r'"C:\Program Files\Google\Chrome\Application\chrome.exe" --version 2>&1', timeout=10)
o3 = out3.read().decode('utf-8', errors='replace')
print(f'\nChrome version: {o3}')

# Check chromedriver version in venv
_, out4, _ = c.exec_command(r'C:\CRAWL_STS\Acc1\DEPLOY_ACC_1\venv\Scripts\python.exe -c "import undetected_chromedriver as uc; print(uc.__version__)"', timeout=15)
o4 = out4.read().decode('utf-8', errors='replace')
print(f'undetected_chromedriver version: {o4}')

c.close()
