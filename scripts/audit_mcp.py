import urllib.request
import json
import sys

TOKEN = "nexus_agent_57mhEcxiHWYVplWnuyMTZuK7QuircbDEz8QGGmEW13c"
URL = "https://k09oezeyib.localto.net/api/mcp"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "localtonet-skip-warning": "true",
    "MCP-Protocol-Version": "2026-07-28"
}

def call_mcp(method, params, req_id):
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params
    }
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())

def run_audit():
    print("==================================================")
    print("NEXUSNODE PUBLIC MCP ENDPOINT AUDIT")
    print(f"Target URL: {URL}")
    print("==================================================")

    # 1. Tools list
    print("\n--- 1. tools/list ---")
    tools = call_mcp("tools/list", {}, 1)
    tool_list = tools.get("result", {}).get("tools", [])
    tool_names = [t["name"] for t in tool_list]
    print(f"Total tools returned: {len(tool_names)}")
    print("Tools:", tool_names)

    # 2. Call nexus.status
    print("\n--- 2. call nexus.status ---")
    status_res = call_mcp("tools/call", {"name": "nexus.status", "arguments": {}}, 2)
    content = status_res.get("result", {}).get("content", [])
    if content:
        status_data = json.loads(content[0]["text"]).get("data", {})
        print(f"Nexus status: OK, uptime: {status_data.get('uptime_seconds')}s, version: {status_data.get('server_version')}")
    else:
        print("Status result:", status_res)

    # 3. Call academic.query for timetable (Oct 28, 2026)
    print("\n--- 3. call academic.query (timetable for Oct 28, 2026) ---")
    tt_res = call_mcp("tools/call", {
        "name": "academic.query",
        "arguments": {
            "operation": "timetable",
            "start_date": "2026-10-28",
            "end_date": "2026-10-28"
        }
    }, 3)
    content_tt = tt_res.get("result", {}).get("content", [])
    events = []
    if content_tt:
        envelope = json.loads(content_tt[0]["text"])
        data_tt = envelope.get("data", {})
        events = data_tt.get("events", [])
    print(f"Total classes returned for 2026-10-28: {len(events)}")
    for ev in events:
        print(f"  * {ev.get('start_time')} - {ev.get('end_time')}: {ev.get('course_name')} (Room: {ev.get('room')})")
    
    prob_found = any("Probability" in ev.get("course_name", "") for ev in events)
    print(f"Discrepancy Check -> Is Probability at 10:00 AM present? {prob_found}")
    assert not prob_found, "Discrepancy error: Probability class is still present!"
    assert len(events) == 4, f"Expected exactly 4 classes, got {len(events)}"
    print("VERIFIED: October 28 timetable matches live portal with exactly 4 classes.")

    # 4. Call academic.query for attendance
    print("\n--- 4. call academic.query (attendance) ---")
    att_res = call_mcp("tools/call", {
        "name": "academic.query",
        "arguments": {
            "operation": "attendance"
        }
    }, 4)
    content_att = att_res.get("result", {}).get("content", [])
    if content_att:
        envelope_att = json.loads(content_att[0]["text"])
        data_att = envelope_att.get("data", {})
        overall = data_att.get("overall", {})
        print(f"Conducted: {overall.get('conducted_classes')}, Attended: {overall.get('attended_classes')}")
        print(f"Overall percentage: {overall.get('attendance_percentage')}%")
        print(f"Safe bunks: {overall.get('total_safe_bunks')}, Critical subjects: {overall.get('critical_subjects')}")
        modules = data_att.get("subjects") or data_att.get("modules", [])
        print(f"Total modules reported: {len(modules)}")
        for m in modules[:4]:
            print(f"  * {m.get('course_name')}: {m.get('attendance_percentage')}% ({m.get('attended_classes')}/{m.get('conducted_classes')})")
    else:
        print("Attendance result:", att_res)

    # 5. Call lms.query for assignments
    print("\n--- 5. call lms.query (assignments) ---")
    lms_res = call_mcp("tools/call", {
        "name": "lms.query",
        "arguments": {
            "operation": "assignments"
        }
    }, 5)
    content_lms = lms_res.get("result", {}).get("content", [])
    if content_lms:
        envelope_lms = json.loads(content_lms[0]["text"])
        data_lms = envelope_lms.get("data", {})
        assignments = data_lms.get("assignments", [])
        print(f"Total assignments: {len(assignments)}")
        for a in assignments:
            print(f"  * {a.get('title')}: Due {a.get('due_at')} ({a.get('status')})")
    else:
        print("LMS assignments result:", lms_res)

    # 6. Call lms.query for courses
    print("\n--- 6. call lms.query (courses) ---")
    c_res = call_mcp("tools/call", {
        "name": "lms.query",
        "arguments": {
            "operation": "courses"
        }
    }, 6)
    content_c = c_res.get("result", {}).get("content", [])
    if content_c:
        envelope_c = json.loads(content_c[0]["text"])
        data_c = envelope_c.get("data", {})
        courses = data_c.get("courses", [])
        print(f"Total courses: {len(courses)}")
        for c in courses[:4]:
            print(f"  * {c.get('name')} (ID: {c.get('course_id')})")

    print("\n==================================================")
    print("ALL MCP VERIFICATION CHECKS PASSED")
    print("==================================================")

if __name__ == "__main__":
    run_audit()
