import requests
import json

endpoints = [
    ("course-summary", "GET", "https://myupes-beta.upes.ac.in/apigateway/connect-portal/api/studentprogramprogress/course-summary/3a678d8e-8817-41e6-b1a8-5a3ec6ee4948", None),
    ("term-wise-course", "GET", "https://myupes-beta.upes.ac.in/apigateway/connect-portal/api/studentprogramprogress/term-wise-course/3a678d8e-8817-41e6-b1a8-5a3ec6ee4948/1", None),
    ("term-wise-all-course", "GET", "https://myupes-beta.upes.ac.in/apigateway/connect-portal/api/studentprogramprogress/term-wise-all-course/3a678d8e-8817-41e6-b1a8-5a3ec6ee4948/1", None),
    ("exam-pro", "POST", "https://myupes-beta.upes.ac.in/apigateway/integratons/api/data/exam-pro", {"StudentUniqueId": "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948", "TermCode": "SEM_1", "ActivityCode": "transcript"})
]

headers = {
    "x-applicationname": "connectportal",
    "x-requestfrom": "web",
    "x-appsecret": "ku7GUMtyT8er51rTfTc7HC",
    "x-studentUniqueId": "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948",
    "Content-Type": "application/json"
}

for name, method, url, payload in endpoints:
    print(f"\nTesting {name} ({method} {url})...")
    try:
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=10)
        else:
            r = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"Status: {r.status_code}")
        print("Headers:", dict(r.headers))
        print("Body:", r.text[:300])
    except Exception as e:
        print("Err:", e)
