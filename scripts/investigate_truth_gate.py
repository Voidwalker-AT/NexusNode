import sys
import os
import json
import sqlite3
import re
import paramiko

sys.path.insert(0, os.path.abspath('.'))
sys.stdout.reconfigure(encoding='utf-8')

def investigate_a():
    print("=== TRUTH GATE A: SEMANTIC MCP CATALOG ===")
    import agent.semantic_facade as sf
    local_tools = [t['name'] for t in sf.SEMANTIC_TOOL_DEFINITIONS]
    print(f"Local semantic tools count: {len(local_tools)}")
    for t in local_tools:
        print(f"  - {t}")
    
    # Check live BG6
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005')
    stdin, stdout, stderr = ssh.exec_command('cd ~/nexusnode && python -c "import agent.semantic_facade as sf; print([t[\'name\'] for t in sf.SEMANTIC_TOOL_DEFINITIONS])"')
    remote_out = stdout.read().decode().strip()
    print(f"Remote BG6 semantic tools: {remote_out}")
    ssh.close()
    return local_tools

def investigate_b():
    print("\n=== TRUTH GATE B: consequential_audit_log ===")
    db_path = "storage_vault/nexus_unified.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # 1. Schema definition
    cur.execute("SELECT sql FROM sqlite_master WHERE name='consequential_audit_log'")
    schema = cur.fetchone()
    print("Schema in DB:\n", schema[0] if schema else "NOT FOUND")
    
    # 2. Row count
    if schema:
        cur.execute("SELECT count(*) FROM consequential_audit_log")
        print("Row count:", cur.fetchone()[0])
    
    conn.close()

    # 3. Search codebase for references to consequential_audit_log
    print("\nSearching codebase for 'consequential_audit_log':")
    matches = []
    for root, dirs, files in os.walk('.'):
        if any(x in root for x in ['.git', '.pytest_cache', '__pycache__', 'storage_vault/backups', 'dist']):
            continue
        for f in files:
            if f.endswith(('.py', '.sql', '.json', '.md', '.html', '.js')):
                p = os.path.join(root, f)
                try:
                    with open(p, 'r', encoding='utf-8', errors='ignore') as fp:
                        for line_no, line in enumerate(fp, 1):
                            if 'consequential_audit_log' in line:
                                matches.append((p, line_no, line.strip()))
                except Exception as e:
                    pass
    print(f"Found {len(matches)} occurrences of 'consequential_audit_log':")
    for m in matches[:15]:
        print(f"  {m[0]}:{m[1]} -> {m[2][:80]}")

def investigate_c():
    print("\n=== TRUTH GATE C: browser/pinchtab.py ===")
    exists = os.path.exists("browser/pinchtab.py")
    print("browser/pinchtab.py exists:", exists)
    
    matches = []
    for root, dirs, files in os.walk('.'):
        if any(x in root for x in ['.git', '.pytest_cache', '__pycache__', 'storage_vault/backups', 'dist']):
            continue
        for f in files:
            if f.endswith(('.py', '.json', '.md', '.sh')):
                p = os.path.join(root, f)
                try:
                    with open(p, 'r', encoding='utf-8', errors='ignore') as fp:
                        for line_no, line in enumerate(fp, 1):
                            if 'pinchtab' in line.lower():
                                matches.append((p, line_no, line.strip()))
                except Exception as e:
                    pass
    print(f"Found {len(matches)} occurrences of 'pinchtab':")
    for m in matches:
        print(f"  {m[0]}:{m[1]} -> {m[2][:80]}")

def investigate_d():
    print("\n=== TRUTH GATE D: CLI COMMANDS ===")
    cli_cmds = ['ai.py', 'models.py', 'rag.py', 'media.py']
    for cmd in cli_cmds:
        path = os.path.join('nexus', 'commands', cmd)
        print(f"\nChecking {path} (exists: {os.path.exists(path)}):")
        # Check callers/imports
        matches = []
        name = cmd.replace('.py', '')
        for root, dirs, files in os.walk('nexus'):
            for f in files:
                if f.endswith('.py'):
                    p = os.path.join(root, f)
                    with open(p, 'r', encoding='utf-8', errors='ignore') as fp:
                        for line_no, line in enumerate(fp, 1):
                            if f'commands.{name}' in line or f'commands/{name}' in line or f'cli.add_command({name}' in line or f'cli.add_command' in line and name in line:
                                matches.append((p, line_no, line.strip()))
        print(f"  Registrations in nexus/: {len(matches)}")
        for m in matches:
            print(f"    {m[0]}:{m[1]} -> {m[2]}")

def investigate_e():
    print("\n=== TRUTH GATE E: DATABASE TABLE COUNT ===")
    conn = sqlite3.connect("storage_vault/nexus_unified.db")
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    print(f"Total tables: {len(tables)}")
    conn.close()
    for t in tables:
        print(f"  - {t}")

if __name__ == "__main__":
    investigate_a()
    investigate_b()
    investigate_c()
    investigate_d()
    investigate_e()
