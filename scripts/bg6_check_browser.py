import sys, os, json
sys.path.insert(0, '/data/data/com.termux/files/home/server')
import app

health = app.browser_service.get_health()
print("BROWSER SERVICE HEALTH:", json.dumps(health, indent=2))
