import paramiko
import os

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.29.21', port=8022, username='u0_a208', password=os.environ.get('BG6_SSH_PASSWORD', 'anmol2005'), timeout=10)

py_code = """
import sqlite3
conn = sqlite3.connect('/data/data/com.termux/files/home/server/storage_vault/nexus_unified.db')
cur = conn.cursor()
cur.execute('SELECT id, client_id, redirect_uri, updated_at FROM google_oauth_app_config')
rows = cur.fetchall()
print('GOOGLE_OAUTH_APP_CONFIG:')
for r in rows:
    print(f'  ID: {r[0]}, ClientID: {r[1][:15]}..., RedirectURI: {r[2]}')
conn.close()
"""

stdin, stdout, stderr = client.exec_command('python3')
stdin.write(py_code)
stdin.channel.shutdown_write()
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    print("STDERR:", err)
client.close()
