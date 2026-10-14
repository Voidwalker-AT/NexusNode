import requests
import re

url = "https://myupes-beta.upes.ac.in/oneportal/main.426c47ea799ff4e6.js"
r = requests.get(url, timeout=30)
text = r.text

matches = [m.start() for m in re.finditer(r'loginUser\(', text)]
for pos in matches:
    print("--- LOGINUSER CALLER ---")
    print(text[max(0, pos-400):min(len(text), pos+400)])

matches_ref = [m.start() for m in re.finditer(r'references', text)]
for pos in matches_ref[:3]:
    print("--- REFERENCES ---")
    print(text[max(0, pos-100):min(len(text), pos+200)])
