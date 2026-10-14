import requests
import re

url = "https://myupes-beta.upes.ac.in/oneportal/254.a15b84e8b3b85014.js"
r = requests.get(url, timeout=30)
text = r.text
print(f"Downloaded 254: len={len(text)}")

# Find login form submit
matches = [m.start() for m in re.finditer(r'loginUser', text)]
print("loginUser count in 254:", len(matches))
for pos in matches:
    print("--- LOGINUSER CALL IN 254 ---")
    print(text[max(0, pos-300):min(len(text), pos+400)])

# Find captcha references in 254
captchas = [m.start() for m in re.finditer(r'captcha', text, re.I)]
print("Captcha count in 254:", len(captchas))
for pos in captchas[:5]:
    print("--- CAPTCHA IN 254 ---")
    print(text[max(0, pos-200):min(len(text), pos+200)])
