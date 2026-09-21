import requests
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

base_public = 'https://k09oezeyib.localto.net'
headers = {'localtonet-skip-warning': 'true'}

endpoints = [
    '/mcp',
    '/api/mcp',
    '/mcp/health',
    '/api/mcp/health',
    '/.well-known/oauth-protected-resource',
    '/.well-known/oauth-protected-resource/api/mcp',
    '/.well-known/oauth-protected-resource/mcp',
    '/.well-known/oauth-authorization-server',
    '/.well-known/openid-configuration'
]

print('=== MCP CANONICAL URL & METADATA PROBE ===')
for ep in endpoints:
    url = f"{base_public}{ep}"
    try:
        r = requests.get(url, headers=headers, timeout=8)
        ct = r.headers.get("Content-Type", "")
        proto = r.headers.get("MCP-Protocol-Version", "none")
        import re
        m = re.search(r"<title>(.*?)</title>", r.text, re.IGNORECASE)
        title = m.group(1) if m else "No title"
        print(f"{ep:45} -> HTTP {r.status_code} | proto: {proto} | title: {title}")
        if r.status_code == 200 and "json" in ct:
            data = r.json()
            if "resource" in data:
                print(f"   Resource: {data['resource']} | Auth servers: {data.get('authorization_servers')}")
            if "issuer" in data:
                print(f"   Issuer: {data['issuer']} | Token: {data.get('token_endpoint')}")
            if "status" in data:
                print(f"   Status: {data.get('status')} | Version: {data.get('server_version')} | Tools: {data.get('tools_count')}")
    except Exception as e:
        print(f"{ep:45} -> ERROR: {e}")
