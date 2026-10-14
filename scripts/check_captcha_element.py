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

bprovider = BG6EphemeralCDPProvider()
svc = agent.BrowserService(provider=bprovider)

res = svc.open_session('admin', {'url': 'https://myupes-beta.upes.ac.in/oneportal/app/auth/login'})
if not res.ok:
    exit(1)

sid = res.data['session_id']
time.sleep(10)

runtime = bprovider._get_runtime(sid)

captcha_info = runtime.cdp_client.call('Runtime.evaluate', {'expression': '''
    (() => {
        const rc = document.querySelector('re-captcha, [formcontrolname=\"recaptcha\"], .g-recaptcha, iframe[src*=\"recaptcha\"]');
        const iframes = Array.from(document.querySelectorAll('iframe')).map(f => f.src);
        const scripts = Array.from(document.querySelectorAll('script')).map(s => s.src).filter(s => s.includes('google') || s.includes('captcha'));
        return {
            recaptchaElement: rc ? rc.outerHTML.substring(0, 300) : null,
            iframes: iframes,
            scripts: scripts,
            windowGrecaptcha: typeof window.grecaptcha !== 'undefined'
        };
    })()
''', 'returnByValue': True})

print('CAPTCHA INFO:', json.dumps(captcha_info.get('result', {}).get('value', {}), indent=2))

svc.close_session('admin', {'session_id': sid})
"
"""

stdin, stdout, stderr = ssh.exec_command('bash -u')
stdin.write(script)
stdin.channel.shutdown_write()
print(stdout.read().decode())
print('STDERR:', stderr.read().decode())
ssh.close()
