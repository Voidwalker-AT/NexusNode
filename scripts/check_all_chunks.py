import requests
import re

chunks = {
    31: "8ba76d28d502b4ca",
    113: "c89658f7761954c2",
    254: "a15b84e8b3b85014",
    361: "61d573e439fa2296",
    393: "edc21b9b090e6c51",
    503: "672bbb3453ed0ed9",
    789: "f31ba31dd5b5ae56"
}

for c_id, c_hash in chunks.items():
    url = f"https://myupes-beta.upes.ac.in/oneportal/{c_id}.{c_hash}.js"
    r = requests.get(url, timeout=15)
    has_login = "login" in r.text.lower()
    has_captcha = "captcha" in r.text.lower()
    has_form = "password" in r.text.lower()
    print(f"Chunk {c_id}: len={len(r.text)} login={has_login} captcha={has_captcha} password={has_form}")
    if has_captcha or (has_login and has_form):
        # find snippets
        for m in re.finditer(r'login', r.text, re.I):
            pos = m.start()
            print(f"  Snippet in {c_id}: {r.text[max(0, pos-100):min(len(r.text), pos+200)]}")
            break
