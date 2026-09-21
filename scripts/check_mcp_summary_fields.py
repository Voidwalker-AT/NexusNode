import requests

base = "https://k09oezeyib.localto.net"
login = requests.post(f"{base}/api/auth/login", headers={"Content-Type": "application/json", "localtonet-skip-warning": "true"}, json={"user_id": "testadmin", "password": "Admin@1234"})
tok = login.json()["token"]

r = requests.get(f"{base}/api/mcp/summary", headers={"Authorization": f"Bearer {tok}", "localtonet-skip-warning": "true"})
print("Status:", r.status_code)
d = r.json()
for k in ["ingress", "public_mcp_url", "lan_mcp_url", "public_endpoint", "public_origin", "lan_origin", "is_public_healthy", "tunnel_provider", "tunnel_status"]:
    print(f"  {k:20}: {d.get(k)}")
