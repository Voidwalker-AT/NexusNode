import requests
import re

url = "https://myupes-beta.upes.ac.in/oneportal/361.61d573e439fa2296.js"
r = requests.get(url, timeout=15)
text = r.text

matches = [m.start() for m in re.finditer(r'isCaptchaEnabled', text)]
for pos in matches:
    print("--- ISCAPTCHAENABLED ---")
    print(text[max(0, pos-150):min(len(text), pos+200)])
