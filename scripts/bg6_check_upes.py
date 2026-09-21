import sys, os, sqlite3, json, time
sys.path.insert(0, '/data/data/com.termux/files/home/server')
import app, config

print("=== CHECKING UPES AUTH STATUS FOR ADMIN ===")
status = app.upes_auth_manager.get_status("admin")
sanitized = {k: v for k, v in status.items() if not any(s in k.lower() for s in ['token', 'password', 'secret', 'cookie'])}
print("STATUS:", json.dumps(sanitized, indent=2))

print("\n=== CHECKING SESSION DETAILS ===")
sess = app.upes_auth_manager.get_session("admin")
if sess:
    print("Has session: True")
    print("Username:", sess.username[:3] + "..." if sess.username else None)
    print("Has access token:", bool(sess.access_token))
    rem = (sess.token_expiry - time.time()) if sess.token_expiry else 0
    print(f"Token expiry: {sess.token_expiry} (remaining: {int(rem)}s)")
    cookie_names = list(sess.cookies.keys()) if sess.cookies else []
    print("Cookie names:", cookie_names)
else:
    print("Has session: False")
