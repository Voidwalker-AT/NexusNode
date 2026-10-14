import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

script = """
export PATH=/data/data/com.termux/files/usr/bin:$PATH
cd ~/server
python3 -c "
import time, json
import agent
from browser.bg6_cdp import BG6EphemeralCDPProvider

provider = BG6EphemeralCDPProvider()
svc = agent.BrowserService(provider=provider)

print('OPENING SESSION...')
res = svc.open_session('admin', {'url': 'https://myupes-beta.upes.ac.in/oneportal/app/auth/login'})
print('OPEN RESULT:', res.ok, res.error, res.data)

if res.ok:
    sid = res.data['session_id']
    time.sleep(5)
    
    print('TAKING SNAPSHOT...')
    snap = svc.snapshot('admin', {'session_id': sid})
    print('SNAPSHOT OK:', snap.ok, snap.error)
    if snap.ok:
        print('PAGE TITLE:', snap.data.get('title'))
        print('PAGE URL:', snap.data.get('url'))
        print('ELEMENTS COUNT:', len(snap.data.get('elements', [])))
        for el in snap.data.get('elements', [])[:15]:
            print('  EL:', el.get('tag'), el.get('type'), el.get('text', '')[:40], el.get('attributes', {}).get('name'))
            
    print('CLOSING SESSION...')
    svc.close_session('admin', {'session_id': sid})
"
"""

stdin, stdout, stderr = ssh.exec_command('bash -u')
stdin.write(script)
stdin.channel.shutdown_write()
print(stdout.read().decode())
print('STDERR:', stderr.read().decode())
ssh.close()
