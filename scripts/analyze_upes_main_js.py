import requests
import re

url = "https://myupes-beta.upes.ac.in/oneportal/main.426c47ea799ff4e6.js"
r = requests.get(url, timeout=30)
print(f"Downloaded main.js: length={len(r.text)}")

# Find mentions of oauth, token, login, captcha, client_id
matches = re.findall(r'[a-zA-Z0-9_\-\./]*oauth[a-zA-Z0-9_\-\./]*', r.text, re.I)
print("OAuth matches:", set(matches[:30]))

matches_api = re.findall(r'"([^"]*api/[^"]*)"', r.text)
print("API matches:", set(matches_api[:30]))

matches_sso = re.findall(r'https?://[^\s"\']+/sso/[^\s"\']+', r.text)
print("SSO URLs:", set(matches_sso))

# Look for captcha logic
captchas = [m.start() for m in re.finditer(r'captcha', r.text, re.I)]
print(f"Captcha count: {len(captchas)}")
for pos in captchas[:5]:
    snippet = r.text[max(0, pos-100):min(len(r.text), pos+150)]
    print("--- CAPTCHA SNIPPET ---")
    print(snippet)

# Look for login submit logic
login_submits = [m.start() for m in re.finditer(r'oauth2/token', r.text, re.I)]
print(f"oauth2/token count: {len(login_submits)}")
for pos in login_submits[:5]:
    snippet = r.text[max(0, pos-150):min(len(r.text), pos+200)]
    print("--- LOGIN SUBMIT SNIPPET ---")
    print(snippet)
