import sys, os, time, logging
sys.path.insert(0, '/data/data/com.termux/files/home/server')
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s")

import app, config

print("=== TESTING BG6 UPES AUTH PIPELINE FOR ADMIN ===")
try:
    status = app.upes_auth_manager.get_status("admin")
    print("Initial status:", status.get("state"))
    tok, student_code, api_url, exp = app.upes_auth_manager.ensure_authenticated("admin")
    rem = exp - time.time()
    print("\n[+] ensure_authenticated SUCCEEDED on BG6!")
    print(f"Token length: {len(tok)}")
    print(f"Student Code (UUID): {student_code}")
    print(f"API URL: {api_url}")
    print(f"Expires in: {int(rem)}s ({rem/3600:.1f}h)")
except Exception as e:
    print(f"\n[-] ensure_authenticated result on BG6: {type(e).__name__}: {e}")
