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

res = svc.open_session('admin', {'url': 'https://myupes-beta.upes.ac.in/oneportal/app/auth/login'})
if res.ok:
    sid = res.data['session_id']
    time.sleep(8)
    
    cap = svc.capture('admin', {'session_id': sid})
    print('CAPTURE OK:', cap.ok, cap.error)
    if cap.ok:
        print('SCREENSHOT PATH:', cap.data.get('screenshot_path'))
        print('HTML LENGTH:', len(cap.data.get('html', '')))
        print('TEXT SNIPPET:', cap.data.get('text', '')[:300])
        print('ELEMENTS COUNT:', len(cap.data.get('elements', [])))
        for el in cap.data.get('elements', []):
            print('  EL:', el.get('ref_id'), el.get('tag'), el.get('type'), el.get('text', '')[:30], el.get('name'))
            
    # Also evaluate JS in the page to see DOM
    if hasattr(provider, 'evaluate_script'):
        js_res = provider.evaluate_script(sid, 'document.body.innerText')
        print('INNER TEXT:', js_res[:300])
        
    svc.close_session('admin', {'session_id': sid})
"
"""

stdin, stdout, stderr = ssh.exec_command('bash -u')
stdin.write(script)
stdin.channel.shutdown_write()
print(stdout.read().decode())
print('STDERR:', stderr.read().decode())
ssh.close()
