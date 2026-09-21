import time
import json
import paramiko

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

    py_code = """
import sqlite3, time, json
import config
import requests
from timetable_sync import TimetableService, GoogleCalendarClient, OAuthTokenCrypto

conn_factory = lambda: sqlite3.connect(config.DB_PATH)
svc = TimetableService(conn_factory)

oauth_info = svc.get_oauth_tokens('admin')
assert oauth_info is not None, "Google OAuth tokens not found for admin"
token_data, cal_id, stored_email = oauth_info

was_expired = time.time() >= (token_data.get('expires_at', 0) - 60)

refreshed = False
def on_refresh(u_id, new_tokens):
    global refreshed
    refreshed = True
    svc.save_oauth_tokens(u_id, new_tokens, cal_id, stored_email)

client = GoogleCalendarClient(token_data, 'admin', on_token_refresh=on_refresh, conn_factory=conn_factory)

# 1. Test token validity / refresh
if was_expired:
    fresh_tok = client.refresh_access_token()
    token_valid = bool(fresh_tok)
else:
    token_valid = True

# 2. Query target calendar metadata
r_cal = client._request('GET', f'/calendars/{requests.utils.quote(cal_id)}')
cal_data = r_cal.json()
cal_exists = r_cal.status_code == 200
cal_tz = cal_data.get('timeZone')
cal_summary = cal_data.get('summary')
cal_primary_id = cal_data.get('id')

# 3. Query calendarList to verify accessRole (writable)
r_list = client._request('GET', '/users/me/calendarList')
list_data = r_list.json()
items = list_data.get('items', [])
target_item = next((c for c in items if c.get('id') == cal_id or (cal_id == 'primary' and c.get('primary'))), None)
access_role = target_item.get('accessRole') if target_item else cal_data.get('accessRole', 'unknown')
is_writable = access_role in ('owner', 'writer')

# Determine user email
account_email = stored_email
if not account_email and cal_primary_id and '@' in cal_primary_id:
    account_email = cal_primary_id
elif not account_email and target_item and '@' in target_item.get('id', ''):
    account_email = target_item.get('id')

# If stored_email was null and we now know the email, update it in DB
if account_email and not stored_email:
    conn = conn_factory()
    conn.execute("UPDATE google_oauth_tokens SET connected_email = ? WHERE user_id = 'admin'", (account_email,))
    conn.execute("UPDATE users SET google_email = ? WHERE user_id = 'admin' AND (google_email IS NULL OR google_email = '')", (account_email,))
    conn.commit()
    conn.close()

out = {
    'token_accepted': token_valid,
    'was_expired': was_expired,
    'refreshed': refreshed,
    'target_calendar_exists': cal_exists,
    'calendar_id': cal_id,
    'calendar_summary': cal_summary,
    'calendar_timezone': cal_tz,
    'access_role': access_role,
    'is_writable': is_writable,
    'account_email': account_email
}
print(json.dumps(out))
"""

    stdin, stdout, stderr = ssh.exec_command("cd ~/server && python3")
    stdin.write(py_code)
    stdin.channel.shutdown_write()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    ssh.close()

    if err:
        print("STDERR:", err)
    print("OUTPUT:", out)

if __name__ == "__main__":
    main()
