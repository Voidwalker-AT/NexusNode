import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', key_filename=os.environ.get("BG6_SSH_KEY", os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) if os.path.exists(os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) else None, password=os.environ.get("BG6_SSH_PASSWORD"), timeout=10)

script = """
export PATH=/data/data/com.termux/files/usr/bin:$PATH
cd ~/server
python3 -c "
import time, json, sqlite3, config
import agent
from browser.bg6_cdp import BG6EphemeralCDPProvider
from upes.credentials import UpesCredentialProvider

def get_db():
    return sqlite3.connect(config.UNIFIED_DB_FILE)

provider = UpesCredentialProvider(get_db)
creds = provider.get_credentials('admin')
if not creds:
    print('NO CREDS')
    exit(1)
username, password = creds
print('GOT CREDS FOR:', username)

bprovider = BG6EphemeralCDPProvider()
svc = agent.BrowserService(provider=bprovider)

res = svc.open_session('admin', {'url': 'https://myupes-beta.upes.ac.in/oneportal/app/auth/login'})
if not res.ok:
    print('FAILED OPEN:', res.error)
    exit(1)

sid = res.data['session_id']
time.sleep(10)

runtime = bprovider._get_runtime(sid)

# Enable Network to capture cookies and responses
runtime.cdp_client.call('Network.enable', {})

# Fill inputs using JS
fill_js = f'''
(() => {{
    const uInput = document.querySelector('input[name=\"userName\"], input[formcontrolname=\"userName\"]');
    const pInput = document.querySelector('input[name=\"password\"], input[formcontrolname=\"password\"]');
    if (!uInput || !pInput) return {{ error: 'inputs not found' }};
    
    uInput.value = {json.dumps(username)};
    uInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
    uInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
    
    pInput.value = {json.dumps(password)};
    pInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
    pInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
    
    const btn = document.querySelector('button[type=\"submit\"]');
    const form = document.querySelector('form');
    
    return {{
        uVal: uInput.value,
        pValLen: pInput.value.length,
        btnDisabled: btn ? btn.disabled : null,
        formClass: form ? form.className : null
    }};
}})()
'''

fill_res = runtime.cdp_client.call('Runtime.evaluate', {'expression': fill_js, 'returnByValue': True})
print('FILL RESULT:', json.dumps(fill_res.get('result', {}).get('value', {}), indent=2))

time.sleep(1)

# Click submit button
click_js = '''
(() => {
    const btn = document.querySelector('button[type=\"submit\"]');
    if (btn) {
        btn.click();
        return { clicked: true };
    }
    return { clicked: false };
})()
'''
click_res = runtime.cdp_client.call('Runtime.evaluate', {'expression': click_js, 'returnByValue': True})
print('CLICK RESULT:', json.dumps(click_res.get('result', {}).get('value', {}), indent=2))

# Wait for navigation / response
print('WAITING 12 SECONDS FOR LOGIN RESPONSE...')
time.sleep(12)

# Check state after submit
state_js = '''
(() => {
    return {
        url: window.location.href,
        title: document.title,
        bodyText: document.body.innerText.substring(0, 500),
        sessionStorageKeys: Object.keys(sessionStorage),
        localStorageKeys: Object.keys(localStorage),
        cookies: document.cookie
    };
})()
'''
state_res = runtime.cdp_client.call('Runtime.evaluate', {'expression': state_js, 'returnByValue': True})
print('STATE AFTER LOGIN:', json.dumps(state_res.get('result', {}).get('value', {}), indent=2))

# Check Network cookies via CDP
cdp_cookies = runtime.cdp_client.call('Network.getCookies', {'urls': ['https://myupes-beta.upes.ac.in']})
cookie_list = cdp_cookies.get('result', {}).get('cookies', [])
print('CDP COOKIES:', [(c.get('name'), c.get('domain'), c.get('expires')) for c in cookie_list])

# Check localStorage and sessionStorage for tokens
token_js = '''
(() => {
    const tokens = {};
    for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        tokens['local_' + k] = localStorage.getItem(k).substring(0, 100);
    }
    for (let i = 0; i < sessionStorage.length; i++) {
        const k = sessionStorage.key(i);
        tokens['session_' + k] = sessionStorage.getItem(k).substring(0, 100);
    }
    return tokens;
})()
'''
token_res = runtime.cdp_client.call('Runtime.evaluate', {'expression': token_js, 'returnByValue': True})
print('TOKENS FOUND:', json.dumps(token_res.get('result', {}).get('value', {}), indent=2))

svc.close_session('admin', {'session_id': sid})
"
"""

stdin, stdout, stderr = ssh.exec_command('bash -u')
stdin.write(script)
stdin.channel.shutdown_write()
print(stdout.read().decode())
print('STDERR:', stderr.read().decode())
ssh.close()
