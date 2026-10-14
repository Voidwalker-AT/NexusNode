import requests
import json

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://myupes-beta.upes.ac.in",
    "Referer": "https://myupes-beta.upes.ac.in/oneportal/app/auth/login"
})

# 1. Visit login page to establish session/cookies
r0 = session.get("https://myupes-beta.upes.ac.in/oneportal/app/auth/login")
print("R0 cookies:", session.cookies.get_dict())

# 2. Get credentials from DB via paramiko or local
# We know the username is student.test@stu.upes.ac.in
# Let's test with a dummy password first or see how it responds without AppRef
payload = {
    "UserId": "student.test@stu.upes.ac.in",
    "Password": "wrongpassword123",
    "Captcha": "-",
    "RememberMe": False
}

headers = {
    "Content-Type": "application/json",
    "X-AppSecret": ""
}

r1 = session.post("https://myupes-beta.upes.ac.in/sso/api/account/oauth2/token", json=payload, headers=headers)
print("R1 status:", r1.status_code)
print("R1 text:", r1.text[:500])
print("R1 cookies:", session.cookies.get_dict())
