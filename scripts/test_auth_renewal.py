import sys, os, time, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s")

import app, config

print("=== TESTING UPES AUTH RENEWAL PIPELINE (force_login=True) ===")
try:
    tok, student_code, api_url, exp = app.upes_auth_manager.ensure_authenticated("admin", force_login=True)
    rem = exp - time.time()
    print("\n[+] ensure_authenticated SUCCEEDED!")
    print(f"Token length: {len(tok)}")
    print(f"Student Code (UUID): {student_code}")
    print(f"API URL: {api_url}")
    print(f"Expires at: {exp} (remaining: {int(rem)}s / {rem/3600:.1f}h)")
except Exception as e:
    print(f"\n[-] ensure_authenticated FAILED: {type(e).__name__}: {e}")
