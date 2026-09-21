"""
NexusNode — Database Migration 002 Runner & Verifier
Phase 4.2C: Evidence-Gated Legacy Retirement
Safely drops ai_inference_metrics and user_chats with integrity checks.
"""

import os
import sys
import json
import sqlite3
import hashlib

def run_migration(db_path: str, migration_sql_path: str, dry_run: bool = False):
    print(f"=== Running Migration 002 on: {db_path} ===")
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")
    if not os.path.exists(migration_sql_path):
        raise FileNotFoundError(f"Migration file not found: {migration_sql_path}")

    with open(migration_sql_path, "r", encoding="utf-8") as f:
        sql = f.read()

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        # 1. Pre-migration integrity check
        cur.execute("PRAGMA integrity_check;")
        pre_integrity = cur.fetchone()[0]
        print(f"Pre-migration integrity check: {pre_integrity}")
        if pre_integrity != "ok":
            raise RuntimeError(f"Database integrity check failed before migration: {pre_integrity}")

        # 2. Get initial table list
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        pre_tables = [r[0] for r in cur.fetchall()]
        print(f"Total tables before: {len(pre_tables)}")

        # 3. Verify target row counts are 0
        for target in ["ai_inference_metrics", "user_chats"]:
            if target in pre_tables:
                cur.execute(f"SELECT COUNT(*) FROM {target};")
                count = cur.fetchone()[0]
                print(f"Table '{target}' row count: {count}")
                if count > 0:
                    raise RuntimeError(f"CRITICAL: Table '{target}' has {count} rows! Refusing to drop non-empty table.")
            else:
                print(f"Table '{target}' does not exist (already dropped).")

        # 4. Verify consequential_audit_log is preserved
        if "consequential_audit_log" not in pre_tables:
            print("WARNING: consequential_audit_log not found in database.")
        else:
            print("Verified: consequential_audit_log is present and will be PRESERVED.")

        if dry_run:
            print("[DRY RUN] Migration would execute:")
            print(sql)
            return {"ok": True, "dry_run": True}

        # 5. Execute migration
        cur.executescript(sql)
        conn.commit()

        # 6. Post-migration integrity check
        cur.execute("PRAGMA integrity_check;")
        post_integrity = cur.fetchone()[0]
        print(f"Post-migration integrity check: {post_integrity}")
        if post_integrity != "ok":
            raise RuntimeError(f"Database integrity check failed after migration: {post_integrity}")

        # 7. Get final table list
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        post_tables = [r[0] for r in cur.fetchall()]
        print(f"Total tables after: {len(post_tables)}")

        dropped = set(pre_tables) - set(post_tables)
        print(f"Dropped tables: {dropped}")

        # Verify dropped matches expected
        for target in ["ai_inference_metrics", "user_chats"]:
            if target in post_tables:
                raise RuntimeError(f"Table '{target}' still present after migration!")

        # Verify consequential_audit_log is still there
        if "consequential_audit_log" in pre_tables and "consequential_audit_log" not in post_tables:
            raise RuntimeError("CRITICAL: consequential_audit_log was accidentally dropped!")

        print("=== Migration 002 SUCCESS ===")
        return {
            "ok": True,
            "pre_integrity": pre_integrity,
            "post_integrity": post_integrity,
            "pre_table_count": len(pre_tables),
            "post_table_count": len(post_tables),
            "dropped_tables": list(dropped),
            "remaining_tables": post_tables
        }
    finally:
        conn.close()

if __name__ == "__main__":
    db_file = sys.argv[1] if len(sys.argv) > 1 else "storage_vault/nexus_unified.db"
    mig_file = sys.argv[2] if len(sys.argv) > 2 else "migrations/002_drop_legacy_ai_tables.sql"
    is_dry = "--dry-run" in sys.argv
    res = run_migration(db_file, mig_file, dry_run=is_dry)
    print(json.dumps(res, indent=2))
