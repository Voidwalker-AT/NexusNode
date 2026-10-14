import requests
import re

url = "https://myupes-beta.upes.ac.in/oneportal/main.426c47ea799ff4e6.js"
r = requests.get(url, timeout=30)
text = r.text

chunks = re.findall(r'(\d+\.[0-9a-f]+\.js)', text)
print("Chunks found:", set(chunks))

# Look for login component
matches = re.findall(r'[a-zA-Z0-9_\$]*Login[a-zA-Z0-9_\$]*', text)
print("Login terms:", set(matches[:40]))
