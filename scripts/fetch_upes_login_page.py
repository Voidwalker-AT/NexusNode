import requests

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9"
})

r = s.get("https://myupes-beta.upes.ac.in/oneportal/app/auth/login", timeout=15)
print("LOGIN PAGE HTTP STATUS:", r.status_code)
print("FINAL URL:", r.url)
print("COOKIES:", s.cookies.get_dict())
print("HTML SNIPPET (first 1000 chars):")
print(r.text[:1000])

import re
scripts = re.findall(r'<script[^>]*src="([^"]+)"', r.text)
print("SCRIPTS:", scripts)
