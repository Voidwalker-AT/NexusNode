import requests

base = 'https://k09oezeyib.localto.net'
headers_init = {'Content-Type': 'application/json', 'localtonet-skip-warning': 'true'}

login_res = requests.post(f"{base}/api/auth/login", headers=headers_init, json={"user_id": "testadmin", "password": "Admin@1234"})
token = login_res.json()["token"]

auth_headers = {'Authorization': f'Bearer {token}', 'localtonet-skip-warning': 'true'}

for ep in ['/files?path=', '/api/system/status', '/api/services/status']:
    r = requests.get(base + ep, headers=auth_headers)
    print(ep, '->', r.status_code, r.text[:80])
