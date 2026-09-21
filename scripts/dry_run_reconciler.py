import paramiko
import json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

py = """
import sqlite3, config, json
from timetable_sync import TimetableService, TimetableSynchronizer, TimetableSession

conn_factory = lambda: sqlite3.connect(config.DB_PATH)
svc = TimetableService(conn_factory)

# 1. Load actual production timetable sessions
sessions, errs = svc.load_timetable_sessions('admin')
unique_sessions, dups = TimetableSynchronizer(conn_factory, 'admin', None).deduplicate_desired_sessions(sessions)

# 2. Inspect existing mapped events
conn = conn_factory()
cur = conn.cursor()
cur.execute("SELECT id, source_session_id, source_date, google_calendar_id, google_event_id, source_hash, summary, start_time, end_time, status FROM timetable_events_map WHERE user_id = 'admin' AND status = 'synced'")
db_rows = cur.fetchall()
conn.close()

# 3. Build a mock client with existing remote events reconstructed from db_rows
mock_events = []
for r in db_rows:
    if r[4]:  # google_event_id
        mock_events.append({
            'id': r[4],
            'summary': r[6],
            'start': {'dateTime': f"{r[2]}T{r[7]}+05:30"},
            'end': {'dateTime': f"{r[2]}T{r[8]}+05:30"},
            'description': f"Managed by: NexusNode\\nSlotKey: {r[1]}",
            'extendedProperties': {
                'private': {
                    'nexusnode_managed': 'true',
                    'nexusnode_slot_key': r[1]
                }
            }
        })

class MockCal:
    def list_managed_events(self, cal_id, time_min=None, time_max=None):
        return mock_events

sync = TimetableSynchronizer(conn_factory, 'admin', MockCal(), 'primary')
plan = sync.synchronize(sessions, dry_run=True, allow_deletions=True)

out = {
    'total_sessions': len(sessions),
    'unique_desired_sessions': len(unique_sessions),
    'existing_mapped_synced': len(db_rows),
    'plan_created': plan.get('created', 0),
    'plan_updated': plan.get('updated', 0),
    'plan_deleted': plan.get('deleted', 0),
    'plan_unchanged': plan.get('unchanged', 0),
    'plan_status': plan.get('status')
}
print(json.dumps(out))
"""

stdin, stdout, stderr = ssh.exec_command("cd ~/server && python3")
stdin.write(py)
stdin.channel.shutdown_write()
out = stdout.read().decode().strip()
err = stderr.read().decode().strip()
ssh.close()

if err:
    print("STDERR:", err)
print("OUTPUT:", out)
