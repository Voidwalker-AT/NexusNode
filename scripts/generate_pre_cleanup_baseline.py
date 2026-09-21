import os
import sys
import json
import sqlite3
import hashlib
import subprocess
import paramiko
import requests

sys.path.insert(0, os.path.abspath('.'))

def run_cmd(cmd):
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return res.stdout.strip(), res.stderr.strip(), res.returncode

def get_git_status():
    stdout, _, _ = run_cmd("git rev-parse HEAD")
    head = stdout
    status_out, _, _ = run_cmd("git status --porcelain")
    changed = [l.strip() for l in status_out.splitlines() if l.strip()]
    return {
        "head_commit": head,
        "dirty_files_count": len(changed),
        "changed_files_sample": changed[:20]
    }

def get_repo_stats():
    total_files = 0
    total_bytes = 0
    source_py_count = 0
    for root, dirs, files in os.walk('.'):
        if any(x in root for x in ['.git', '.pytest_cache', '__pycache__']):
            continue
        for f in files:
            total_files += 1
            p = os.path.join(root, f)
            try:
                sz = os.path.getsize(p)
                total_bytes += sz
                if f.endswith('.py'):
                    source_py_count += 1
            except Exception:
                pass
    return {
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / (1024 * 1024), 2),
        "python_files": source_py_count
    }

def get_test_stats():
    report_path = "scripts/test_execution_report.json"
    if os.path.exists(report_path):
        with open(report_path, 'r') as fp:
            d = json.load(fp)
            return {
                "total_files": d.get("total_files"),
                "total_collected": d.get("total_collected"),
                "total_passed": d.get("total_passed"),
                "total_failed": d.get("total_failed"),
                "total_skipped": d.get("total_skipped"),
                "total_errors": d.get("total_errors"),
                "duration_sec": d.get("total_duration_sec")
            }
    return {}

def get_db_stats():
    db_path = "storage_vault/nexus_unified.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA integrity_check")
    integrity = cur.fetchone()[0]
    
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
    tables_info = cur.fetchall()
    table_names = [t[0] for t in tables_info]
    
    schema_dump = "\n".join([f"{t[0]}:{t[1]}" for t in tables_info if t[1]])
    schema_hash = hashlib.sha256(schema_dump.encode()).hexdigest()
    
    row_counts = {}
    for t in table_names:
        if t.startswith("sqlite_"):
            continue
        try:
            cur.execute(f'SELECT count(*) FROM "{t}"')
            row_counts[t] = cur.fetchone()[0]
        except Exception:
            row_counts[t] = -1
            
    conn.close()
    return {
        "integrity": integrity,
        "schema_hash": schema_hash,
        "total_tables_including_system": len(table_names),
        "user_tables_count": len(row_counts),
        "row_counts": row_counts
    }

def get_bg6_stats():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005')
    
    # PID & RSS
    cmd_ps = "ps -o pid,rss,args -C python"
    _, stdout, _ = ssh.exec_command(cmd_ps)
    ps_out = stdout.read().decode().strip()
    
    # Meminfo
    cmd_mem = "cat /proc/meminfo | grep -E 'MemTotal|MemFree|MemAvailable|SwapTotal|SwapFree'"
    _, stdout, _ = ssh.exec_command(cmd_mem)
    mem_out = stdout.read().decode().strip()
    
    # Disk free
    cmd_df = "df -h /data/data/com.termux/files/home"
    _, stdout, _ = ssh.exec_command(cmd_df)
    df_out = stdout.read().decode().strip()
    
    # Chromium processes
    cmd_chrom = "ps aux | grep -i chromium | grep -v grep | wc -l"
    _, stdout, _ = ssh.exec_command(cmd_chrom)
    chrom_count = stdout.read().decode().strip()
    
    # Services status
    cmd_sv = "sv status nexusnode; sv status localtonet"
    _, stdout, _ = ssh.exec_command(cmd_sv)
    sv_out = stdout.read().decode().strip()
    
    # Server health via loopback
    cmd_curl = "curl -s http://127.0.0.1:5000/health"
    _, stdout, _ = ssh.exec_command(cmd_curl)
    health_out = stdout.read().decode().strip()
    
    ssh.close()
    return {
        "ps": ps_out,
        "meminfo": mem_out,
        "storage": df_out,
        "chromium_processes_count": int(chrom_count) if chrom_count.isdigit() else chrom_count,
        "supervision": sv_out,
        "health": health_out
    }

def get_functional_baseline():
    import app
    client = app.app.test_client()
    
    # 1. Dashboard summary
    dash_resp = client.get("/api/dashboard/summary")
    
    # 2. Tools list via app.mcp_adapter.semantic_facade
    facade = app.mcp_adapter.semantic_facade
    tools = facade.get_tool_definitions(catalog_mode="semantic")
    
    token_meta = {"user_id": "admin", "scopes": ["read", "write", "admin"], "capabilities": ["all"]}
    
    # Helper to check MCP tool result
    def check_res(res_dict):
        if not res_dict or res_dict.get("isError"):
            return False
        content = res_dict.get("content", [])
        if content and isinstance(content[0], dict) and "text" in content[0]:
            try:
                parsed = json.loads(content[0]["text"])
                return parsed.get("ok", True)
            except Exception:
                return True
        return False

    # 3. nexus.status
    stat_res = facade.execute("nexus.status", {}, token_meta)
    
    # 4. academic.query
    acad_res = facade.execute("academic.query", {"operation": "attendance"}, token_meta)
    
    # 5. lms.query
    lms_res = facade.execute("lms.query", {"operation": "courses"}, token_meta)
    
    # 6. vault.manage
    vault_res = facade.execute("vault.manage", {"operation": "list", "path": ""}, token_meta)
    
    return {
        "dashboard_summary_status": dash_resp.status_code,
        "semantic_tools_count": len(tools),
        "semantic_tools": [t["name"] for t in tools],
        "nexus_status_ok": check_res(stat_res),
        "academic_query_ok": check_res(acad_res),
        "lms_query_ok": check_res(lms_res),
        "vault_manage_ok": check_res(vault_res)
    }

def main():
    print("Generating pre-cleanup baseline...")
    baseline = {
        "timestamp": "2026-09-20T19:30:00+05:30",
        "phase": "Phase 4.2C Pre-Cleanup Baseline",
        "git": get_git_status(),
        "repository": get_repo_stats(),
        "test_suite": get_test_stats(),
        "database": get_db_stats(),
        "bg6_appliance": get_bg6_stats(),
        "functional_baseline": get_functional_baseline()
    }
    
    out_file = "scripts/phase42c_pre_cleanup_baseline.json"
    with open(out_file, "w", encoding="utf-8") as fp:
        json.dump(baseline, fp, indent=2)
    print(f"Successfully wrote {out_file}")

if __name__ == "__main__":
    main()
