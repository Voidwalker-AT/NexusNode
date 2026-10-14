import requests
import re

url = "https://myupes-beta.upes.ac.in/oneportal/main.426c47ea799ff4e6.js"
r = requests.get(url, timeout=30)
text = r.text

matches = [m.start() for m in re.finditer(r'path:"auth"', text)]
if not matches:
    matches = [m.start() for m in re.finditer(r'path:"app"', text)]
if not matches:
    matches = [m.start() for m in re.finditer(r'path:"login"', text)]

for pos in matches[:5]:
    print("--- ROUTE TABLE ---")
    print(text[max(0, pos-100):min(len(text), pos+500)])
