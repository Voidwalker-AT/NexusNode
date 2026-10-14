import requests
import re

url = "https://myupes-beta.upes.ac.in/oneportal/main.426c47ea799ff4e6.js"
r = requests.get(url, timeout=30)
text = r.text

matches = [m.start() for m in re.finditer(r'\.loginUser\(', text)]
print("Matches:", len(matches))
for pos in matches:
    print("--- CALL ---")
    print(text[max(0, pos-300):min(len(text), pos+300)])
