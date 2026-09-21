import requests
import json

base_url = "https://k09oezeyib.localto.net"

# 1. Login as testadmin
login_resp = requests.post(
    f"{base_url}/api/auth/login",
    headers={"Content-Type": "application/json", "localtonet-skip-warning": "true"},
    json={"user_id": "testadmin", "password": "Admin@1234"}
)
print("Login status:", login_resp.status_code)
token = login_resp.json().get("token")
print("Session token:", token[:10] + "...")

headers = {
    "Authorization": f"Bearer {token}",
    "localtonet-skip-warning": "true"
}

endpoints = [
    "/api/auth/me",
    "/api/dashboard/summary",
    "/api/timetable/sessions",
    "/api/attendance/summary",
    "/api/academics/results",
    "/api/lms/courses",
    "/api/vault/files",
    "/api/mcp/summary",
    "/api/diagnostics/system",
    "/api/settings",
    "/api/admin/users"
]

print("\n=== PROBING ENDPOINTS AS TESTADMIN OVER PUBLIC INTERNET ===")
for ep in endpoints:
    r = requests.get(f"{base_url}{ep}", headers=headers, timeout=10)
    ct = r.headers.get("Content-Type", "")
    print(f"{ep:30} -> HTTP {r.status_code} | {ct[:25]}")
    if r.status_code == 200 and "json" in ct:
        data = r.json()
        keys = list(data.keys()) if isinstance(data, dict) else f"list(len={len(data)})"
        print(f"   Keys/Summary: {keys}")
    elif r.status_code != 200:
        print(f"   Error: {r.text[:100]}")
