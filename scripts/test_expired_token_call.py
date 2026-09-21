import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sqlite3
import requests
import json

conn = sqlite3.connect("storage_vault/nexus_unified.db")
cur = conn.cursor()
cur.execute("SELECT encrypted_access_token FROM upes_auth_sessions WHERE user_id = 'admin'")
row = cur.fetchone()
conn.close()

from timetable_sync import OAuthTokenCrypto
from upes.crypto import UpesSessionCrypto

dec = UpesSessionCrypto.decrypt(row[0])
tok = dec.get("access_token") if dec else None
if not tok:
    dec = OAuthTokenCrypto.decrypt(row[0])
    tok = dec.get("access_token") if dec else row[0]

print("Token length:", len(tok))

headers = {
    "Authorization": f"Bearer {tok}",
    "x-applicationname": "connectportal",
    "x-requestfrom": "web",
    "x-appsecret": "ku7GUMtyT8er51rTfTc7HC",
    "x-studentUniqueId": "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948",
    "Content-Type": "application/json"
}

url = "https://myupes-beta.upes.ac.in/apigateway/connect-portal/api/studentprogramprogress/course-summary/3a678d8e-8817-41e6-b1a8-5a3ec6ee4948"
print(f"Calling {url} with expired bearer token...")
r = requests.get(url, headers=headers, timeout=10)
print(f"Status: {r.status_code}")
print("Headers:", dict(r.headers))
print("Body:", r.text[:300])
