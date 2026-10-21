import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', key_filename=os.environ.get("BG6_SSH_KEY", os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) if os.path.exists(os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) else None, password=os.environ.get("BG6_SSH_PASSWORD"), timeout=10)

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
    time.sleep(10)
    
    runtime = provider._get_runtime(sid)
    
    # 1. Check title and url
    u = runtime.cdp_client.call('Runtime.evaluate', {'expression': 'window.location.href', 'returnByValue': True})
    t = runtime.cdp_client.call('Runtime.evaluate', {'expression': 'document.title', 'returnByValue': True})
    print('URL:', u.get('result', {}).get('value'))
    print('TITLE:', t.get('result', {}).get('value'))
    
    # 2. Check innerHTML
    html = runtime.cdp_client.call('Runtime.evaluate', {'expression': 'document.body.innerHTML.length', 'returnByValue': True})
    print('HTML LEN:', html.get('result', {}).get('value'))
    
    # 3. Check inputs/forms
    inputs = runtime.cdp_client.call('Runtime.evaluate', {'expression': '''
        (() => {
            const els = Array.from(document.querySelectorAll('input, button, a, form'));
            return els.map(e => ({
                tag: e.tagName,
                id: e.id,
                name: e.name,
                type: e.type,
                text: (e.innerText || e.value || '').trim().substring(0, 50),
                className: e.className
            }));
        })()
    ''', 'returnByValue': True})
    print('INPUTS/BUTTONS:', json.dumps(inputs.get('result', {}).get('value', []), indent=2))
    
    svc.close_session('admin', {'session_id': sid})
"
"""

stdin, stdout, stderr = ssh.exec_command('bash -u')
stdin.write(script)
stdin.channel.shutdown_write()
print(stdout.read().decode())
print('STDERR:', stderr.read().decode())
ssh.close()
