"""
NexusNode — Comprehensive Remote Ingress & Academics Verification on BG6
"""

import os
import sys
import json
import paramiko

def run():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=15)

    def exec_cmd(cmd):
        stdin, stdout, stderr = ssh.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && {cmd}")
        return stdout.read().decode('utf-8', errors='replace').strip(), stderr.read().decode('utf-8', errors='replace').strip()

    print("=" * 60)
    print("1. RUNIT SERVICE STATUS")
    print("=" * 60)
    out, _ = exec_cmd("SVDIR=/data/data/com.termux/files/usr/var/service sv status nexusnode")
    print(out)

    print("\n" + "=" * 60)
    print("2. CHROMIUM PROCESS COUNT INVARIANT")
    print("=" * 60)
    out, _ = exec_cmd("ps aux | grep '[c]hromium' | wc -l")
    count = int(out.strip()) if out.strip().isdigit() else -1
    print(f"Active Chromium process count: {count} (Target: 0)")
    assert count == 0, f"Expected 0 Chromium processes, found {count}"

    print("\n" + "=" * 60)
    print("3. REMOTE UNIT TESTS (test_ingress_and_academics_resilience.py)")
    print("=" * 60)
    out, err = exec_cmd("python -m unittest tests/test_ingress_and_academics_resilience.py")
    print(out)
    if err:
        print(err)

    print("\n" + "=" * 60)
    print("4. LIVE ENDPOINT CONTRACT PROBE VIA BG6 TEST CLIENT")
    print("=" * 60)
    remote_probe = """
import time, json, secrets
import app, config

# Inject admin session token into app.SESSIONS
token = secrets.token_hex(16)
with app.SESSIONS_LOCK:
    app.SESSIONS[token] = {
        'user_id': 'admin',
        'role': 'admin',
        'privileges': dict(config.ADMIN_DEFAULT_PRIVILEGES),
        'created_at': time.time(),
        'expires_at': time.time() + 3600
    }

headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
client = app.app.test_client()

# A. Ingress & MCP Summary
r_mcp = client.get('/api/mcp/summary', headers=headers)
mcp_data = r_mcp.get_json() or {}
ing = mcp_data.get('ingress', {})
print('MCP_SUMMARY_STATUS:', r_mcp.status_code)
print('PUBLIC_MCP_URL:', ing.get('public_mcp_url'))
print('LAN_MCP_URL:', ing.get('lan_mcp_url'))
print('TUNNEL_STATUS:', ing.get('tunnel_status'))
print('IS_PUBLIC_HEALTHY:', ing.get('is_public_healthy'))

# B. OAuth Protected Resource Discovery
r_oauth_res = client.get('/.well-known/oauth-protected-resource/api/mcp')
print('OAUTH_RESOURCE_STATUS:', r_oauth_res.status_code)
print('OAUTH_RESOURCE:', r_oauth_res.get_json())

# C. OAuth Auth Server Discovery
r_oauth_as = client.get('/.well-known/oauth-authorization-server')
print('OAUTH_AUTH_SERVER_STATUS:', r_oauth_as.status_code)
print('OAUTH_ISSUER:', (r_oauth_as.get_json() or {}).get('issuer'))

# D. Timetable Sessions
r_tt = client.get('/api/timetable/sessions', headers=headers)
tt_data = r_tt.get_json() or {}
sessions = tt_data.get('sessions', [])
print('TIMETABLE_STATUS:', r_tt.status_code)
print('TIMETABLE_COUNT:', len(sessions))
print('TIMETABLE_PROVENANCE:', tt_data.get('provenance'))
if sessions:
    s0 = sessions[0]
    print('SAMPLE_SESSION:', {
        'course_name': s0.get('course_name'),
        'start_time': s0.get('start_time'),
        'end_time': s0.get('end_time'),
        'day_of_week': s0.get('day_of_week'),
        'course': s0.get('course'),
        'start': s0.get('start'),
        'weekday': s0.get('weekday')
    })

# E. Attendance Summary
r_att = client.get('/api/attendance/summary', headers=headers)
att_data = r_att.get_json() or {}
summary = att_data.get('summary', {})
reports = att_data.get('subject_reports', [])
print('ATTENDANCE_STATUS:', r_att.status_code)
print('ATTENDANCE_OVERALL:', {
    'conducted': summary.get('conducted_classes'),
    'attended': summary.get('attended_classes'),
    'percentage': summary.get('attendance_percentage'),
    'safe_bunks': summary.get('overall_safe_bunks')
})
print('ATTENDANCE_SUBJECTS_COUNT:', len(reports))
if reports:
    r0 = reports[0]
    print('SAMPLE_REPORT:', {
        'course_name': r0.get('course_name'),
        'conducted': r0.get('conducted_classes'),
        'attended': r0.get('attended_classes'),
        'percentage': r0.get('attendance_percentage'),
        'safe_bunks': r0.get('safe_bunks'),
        'recovery_needed': r0.get('recovery_classes_needed')
    })

# F. Results
r_res = client.get('/api/academics/results', headers=headers)
res_data = r_res.get_json() or {}
print('RESULTS_STATUS:', r_res.status_code)
print('RESULTS_SEMESTERS_COUNT:', len(res_data.get('semesters', [])))
print('RESULTS_CGPA:', res_data.get('cgpa'))

# G. LMS Courses
r_lms = client.get('/api/lms/courses', headers=headers)
lms_data = r_lms.get_json() or {}
print('LMS_STATUS:', r_lms.status_code)
print('LMS_COURSES_COUNT:', len(lms_data.get('courses', [])))
print('LMS_PROVENANCE:', lms_data.get('provenance'))

# Clean up session
with app.SESSIONS_LOCK:
    if token in app.SESSIONS:
        del app.SESSIONS[token]
"""
    out, err = exec_cmd(f'python -c "{remote_probe}"')
    print(out)
    if err:
        print("STDERR:", err)

    ssh.close()
    print("\n" + "=" * 60)
    print("VERIFICATION COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    run()
