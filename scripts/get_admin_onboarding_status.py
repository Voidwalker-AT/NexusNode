import paramiko
import requests
import secrets
import base64
import hashlib
import json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

verifier = secrets.token_urlsafe(32)
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')
client_id = 'test_admin_status'
client_secret = 'sec_admin_999'
redirect_uri = 'https://oauth-redirect.googleusercontent.com/r/test_live'

mint_py = f"""
import sqlite3, config
from agent.oauth_provider import OAuthProvider

conn_factory = lambda: sqlite3.connect(config.DB_PATH)
provider = OAuthProvider(conn_factory=conn_factory)
provider.register_client(
    client_id='{client_id}', client_secret='{client_secret}',
    client_name='Admin Status Check', redirect_uris=['{redirect_uri}']
)
code, _ = provider.create_authorization_code(
    client_id='{client_id}', redirect_uri='{redirect_uri}',
    user_id='admin', scope='mcp',
    code_challenge='{challenge}', code_challenge_method='S256'
)
print('CODE:' + code)
"""

stdin, stdout, stderr = ssh.exec_command("cd ~/server && python3")
stdin.write(mint_py)
stdin.channel.shutdown_write()
out = stdout.read().decode()
code = [l for l in out.splitlines() if l.startswith('CODE:')][0].split(':', 1)[1].strip()
ssh.close()

basic_auth = base64.b64encode(f'{client_id}:{client_secret}'.encode()).decode()
r_tok = requests.post(
    'https://k09oezeyib.localto.net/oauth/token',
    data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri, 'code_verifier': verifier},
    headers={'Authorization': f'Basic {basic_auth}', 'localtonet-skip-warning': 'true'},
    timeout=10
)
tok = r_tok.json()['access_token']

r = requests.get(
    'https://k09oezeyib.localto.net/api/timetable/onboarding-status',
    headers={'Authorization': f'Bearer {tok}', 'localtonet-skip-warning': 'true'},
    timeout=10
)
print('STATUS:', r.status_code)
print(json.dumps(r.json(), indent=2))
