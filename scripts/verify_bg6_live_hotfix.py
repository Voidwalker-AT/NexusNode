"""
NexusNode — Live Hotfix Verification on TECNO BG6
"""

import urllib.request
import urllib.parse
import json

BG6_URL = "http://192.168.29.21:5000"

def get_admin_token():
    # Authenticate as admin
    login_url = f"{BG6_URL}/api/auth/login"
    data = json.dumps({"username": "admin", "password": "adminpassword"}).encode("utf-8")
    req = urllib.request.Request(login_url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("token") or body.get("access_token")
    except Exception as e:
        print(f"Login failed: {e}")
        return None

def main():
    print("=== LIVE PROBE: TECNO BG6 (http://192.168.29.21:5000) ===")
    
    # 1. Health
    with urllib.request.urlopen(f"{BG6_URL}/api/health") as resp:
        health = json.loads(resp.read().decode("utf-8"))
        print(f"1. Health: status={health.get('status')}, version={health.get('version')}")

    # 2. OAuth Discovery (Public/LAN metadata)
    with urllib.request.urlopen(f"{BG6_URL}/.well-known/oauth-protected-resource/api/mcp") as resp:
        disc = json.loads(resp.read().decode("utf-8"))
        print(f"2. OAuth Protected Resource: resource={disc.get('resource')}, auth_servers={disc.get('authorization_servers')}")

    with urllib.request.urlopen(f"{BG6_URL}/.well-known/oauth-authorization-server") as resp:
        auth_disc = json.loads(resp.read().decode("utf-8"))
        print(f"3. OAuth Auth Server: issuer={auth_disc.get('issuer')}, token_endpoint={auth_disc.get('token_endpoint')}")

    token = get_admin_token()
    if not token:
        print("Failed to acquire token, testing with session / direct")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    # 4. MCP Summary
    req = urllib.request.Request(f"{BG6_URL}/api/mcp/summary", headers=headers)
    with urllib.request.urlopen(req) as resp:
        mcp_data = json.loads(resp.read().decode("utf-8"))
        ingress = mcp_data.get("ingress", {})
        print(f"4. MCP Summary Ingress:")
        print(f"   Public MCP URL: {ingress.get('public_mcp_url')}")
        print(f"   LAN MCP URL:    {ingress.get('lan_mcp_url')}")
        print(f"   Tunnel Status:  {ingress.get('tunnel_status')} (is_healthy: {ingress.get('is_public_healthy')})")

    # 5. Timetable Sessions
    req = urllib.request.Request(f"{BG6_URL}/api/timetable/sessions", headers=headers)
    with urllib.request.urlopen(req) as resp:
        tt_data = json.loads(resp.read().decode("utf-8"))
        sessions = tt_data.get("sessions", [])
        print(f"5. Timetable Sessions: count={len(sessions)}, provenance={tt_data.get('provenance')}")
        if sessions:
            s0 = sessions[0]
            print(f"   Sample session: course_name='{s0.get('course_name')}', start='{s0.get('start_time')}', day='{s0.get('day_of_week')}'")

    # 6. Attendance Summary
    req = urllib.request.Request(f"{BG6_URL}/api/attendance/summary", headers=headers)
    with urllib.request.urlopen(req) as resp:
        att_data = json.loads(resp.read().decode("utf-8"))
        summary = att_data.get("summary", {})
        reports = att_data.get("subject_reports", [])
        print(f"6. Attendance Summary: conducted={summary.get('conducted_classes')}, attended={summary.get('attended_classes')}, pct={summary.get('attendance_percentage')}%, subjects={len(reports)}")
        if reports:
            r0 = reports[0]
            print(f"   Sample subject: course_name='{r0.get('course_name')}', safe_bunks={r0.get('safe_bunks')}, pct={r0.get('attendance_percentage')}%")

    # 7. Academics Results
    req = urllib.request.Request(f"{BG6_URL}/api/academics/results", headers=headers)
    with urllib.request.urlopen(req) as resp:
        res_data = json.loads(resp.read().decode("utf-8"))
        sems = res_data.get("semesters", [])
        print(f"7. Results: count={len(sems)}, cgpa={res_data.get('cgpa')}")

    # 8. LMS Courses
    req = urllib.request.Request(f"{BG6_URL}/api/lms/courses", headers=headers)
    with urllib.request.urlopen(req) as resp:
        lms_data = json.loads(resp.read().decode("utf-8"))
        courses = lms_data.get("courses", [])
        print(f"8. LMS Courses: count={len(courses)}, provenance={lms_data.get('provenance')}")

    print("=== LIVE PROBE COMPLETE ===")

if __name__ == "__main__":
    main()
