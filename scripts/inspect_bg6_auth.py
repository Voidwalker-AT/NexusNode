import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', key_filename=os.environ.get("BG6_SSH_KEY", os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) if os.path.exists(os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) else None, password=os.environ.get("BG6_SSH_PASSWORD"), timeout=10)

script = """
export PATH=/data/data/com.termux/files/usr/bin:$PATH
cd ~/server
python3 -c "
import sqlite3, os, config, sys
from upes.credentials import UpesCredentialProvider, UpesCredentialCrypto

def get_db():
    return sqlite3.connect(config.UNIFIED_DB_FILE)

provider = UpesCredentialProvider(get_db)
creds = provider.get_credentials('admin')
if creds:
    u, p = creds
    print('CREDENTIALS FOUND: user=', u, 'pw_length=', len(p))
else:
    print('NO CREDENTIALS FOUND')

# Test direct login or probe UPES SSO
import requests
login_url = getattr(config, 'UPES_SSO_LOGIN_URL', 'https://myupes-beta.upes.ac.in/sso/api/account/oauth2/token')
client_id = getattr(config, 'UPES_SSO_CLIENT_ID', 3)
client_secret = getattr(config, 'UPES_SSO_CLIENT_SECRET', 'ku7GUMtyT8er51rTfTc7HC')

payload = {
    'UserId': u if creds else 'test',
    'Password': p if creds else 'test',
    'Captcha': '-',
    'AppRef': None,
    'RememberMe': False
}
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Content-Type': 'application/json',
    'Origin': 'https://myupes-beta.upes.ac.in',
    'Referer': 'https://myupes-beta.upes.ac.in/oneportal/app/auth/login'
}

print('PROBING SSO LOGIN ENDPOINT:', login_url)
try:
    resp = requests.post(login_url, json=payload, headers=headers, timeout=10)
    print('SSO STATUS CODE:', resp.status_code)
    print('SSO HEADERS:', dict(resp.headers))
    print('SSO BODY:', resp.text[:1000])
except Exception as e:
    print('SSO PROBE ERROR:', e)
"
"""

stdin, stdout, stderr = ssh.exec_command('bash -u')
stdin.write(script)
stdin.channel.shutdown_write()
print(stdout.read().decode())
print('STDERR:', stderr.read().decode())
ssh.close()
