import requests
import re
import json

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

url = "https://myupes-beta.upes.ac.in/connectportal/index.html"
print(f"Fetching {url}...")
resp = session.get(url, allow_redirects=False, timeout=15)
print("Status:", resp.status_code)
print("Headers Location:", resp.headers.get("Location"))
print("Set-Cookie:", resp.headers.get("Set-Cookie"))

html = resp.text
print("HTML length:", len(html))
scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html)
print("\nDiscovered script tags:")
for s in scripts:
    print(" -", s)
