import requests

url = "https://myupes-beta.upes.ac.in/sso/adfs/oauth2/authorize?&hash=abcdef1234567890abcd&client_id=1&clientSecret=MxrMOp8VxmPJ80H52R2D"
s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
})

r = s.get(url, allow_redirects=False)
print("SSO AUTH STATUS:", r.status_code)
print("HEADERS:", dict(r.headers))
if "Location" in r.headers:
    print("LOCATION:", r.headers["Location"])
