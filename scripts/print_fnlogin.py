import requests
import re

url = "https://myupes-beta.upes.ac.in/oneportal/361.61d573e439fa2296.js"
r = requests.get(url, timeout=15)
text = r.text

pos = text.find("fnLogin()")
print("fnLogin snippet:")
print(text[pos:pos+1500])
