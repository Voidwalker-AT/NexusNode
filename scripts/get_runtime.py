import requests
import re

url = "https://myupes-beta.upes.ac.in/oneportal/runtime.6d068266c5202013.js"
r = requests.get(url, timeout=15)
print("Runtime text:")
print(r.text)
