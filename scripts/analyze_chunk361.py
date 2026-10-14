import requests
import re

url = "https://myupes-beta.upes.ac.in/oneportal/361.61d573e439fa2296.js"
r = requests.get(url, timeout=15)
text = r.text
print(f"Chunk 361 len: {len(text)}")

# Find fnLogin definition
matches = [m.start() for m in re.finditer(r'fnLogin', text)]
for pos in matches:
    print("--- FNLOGIN ---")
    print(text[max(0, pos-200):min(len(text), pos+600)])

matches_captcha = [m.start() for m in re.finditer(r'recaptcha', text, re.I)]
for pos in matches_captcha:
    print("--- RECAPTCHA IN 361 ---")
    print(text[max(0, pos-100):min(len(text), pos+300)])
