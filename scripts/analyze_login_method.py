import requests
import re

url = "https://myupes-beta.upes.ac.in/oneportal/main.426c47ea799ff4e6.js"
r = requests.get(url, timeout=30)
text = r.text

# Search for formbasedLoginEndpoint usage
matches = [m.start() for m in re.finditer(r'formbasedLoginEndpoint', text)]
for pos in matches:
    print("--- FORMBASED LOGIN SNIPPET ---")
    print(text[max(0, pos-200):min(len(text), pos+400)])

# Search for IDPConfiguration
matches2 = [m.start() for m in re.finditer(r'IDPConfiguration', text)]
for pos in matches2[:5]:
    print("--- IDPCONFIGURATION SNIPPET ---")
    print(text[max(0, pos-100):min(len(text), pos+300)])

# Search for crypto_key usage
matches3 = [m.start() for m in re.finditer(r'crypto_key', text)]
for pos in matches3:
    print("--- CRYPTO_KEY SNIPPET ---")
    print(text[max(0, pos-100):min(len(text), pos+300)])
