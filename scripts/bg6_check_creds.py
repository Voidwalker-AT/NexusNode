import sys, os, sqlite3, json
sys.path.insert(0, '/data/data/com.termux/files/home/server')
import app, config

conn = sqlite3.connect('/data/data/com.termux/files/home/server/storage_vault/nexus_unified.db')
cur = conn.cursor()
cur.execute("PRAGMA table_info(upes_user_credentials)")
cols = [r[1] for r in cur.fetchall()]
print("CREDS COLS:", cols)
cur.execute(f"SELECT {', '.join([c for c in cols if 'password' not in c and 'secret' not in c and 'key' not in c])} FROM upes_user_credentials")
creds = cur.fetchall()
print("UPES CREDENTIAL ROWS (non-secret):", creds)

cur.execute("PRAGMA table_info(upes_auth_sessions)")
s_cols = [r[1] for r in cur.fetchall()]
print("SESSION COLS:", s_cols)
cur.execute(f"SELECT {', '.join([c for c in s_cols if 'token' not in c and 'cookie' not in c and 'bundle' not in c and 'blob' not in c])} FROM upes_auth_sessions")
sess = cur.fetchall()
print("UPES AUTH SESSIONS (non-secret):", sess)

conn.close()
