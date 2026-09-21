import requests
import json

r = requests.get('https://localtonet.com/swagger/v2/swagger.json')
data = r.json()
print("Swagger API Title:", data.get('info', {}).get('title'))
print("Paths:")
for path, methods in data.get('paths', {}).items():
    for m, details in methods.items():
        summary = details.get('summary') or details.get('operationId')
        print(f"  {m.upper()} {path} - {summary}")

auth_sec = data.get('components', {}).get('securitySchemes', {})
print("\nSecurity Schemes:", auth_sec)
