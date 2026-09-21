"""
NexusNode — Database Migration 003 Runner & Verifier
Phase 4.3A: Academic Results, Grades & Performance Storage
Creates academic_results, academic_result_courses, and academic_result_sync_history tables.
"""

import os
import sys
import json
import sqlite3

def run_migration(db_path: str, migration_sql_path: str, dry_run: bool = False):
    print(f"=== Running Migration 003 on: {db_path} ===")
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

        target_tables = ["academic_results", "academic_result_courses", "academic_result_sync_history"]

        if dry_run:
            print("[DRY RUN] Migration would execute:")
            print(sql)
            return {"ok": True, "dry_run": True}

        # 3. Execute migration
        cur.executescript(sql)
        conn.commit()

        # 4. Post-migration integrity check
        cur.execute("PRAGMA integrity_check;")
        post_integrity = cur.fetchone()[0]
        print(f"Post-migration integrity check: {post_integrity}")
        if post_integrity != "ok":
            raise RuntimeError(f"Database integrity check failed after migration: {post_integrity}")

        # 5. Get final table list
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        post_tables = [r[0] for r in cur.fetchall()]
        print(f"Total tables after: {len(post_tables)}")

        new_tables = set(post_tables) - set(pre_tables)
        print(f"New tables created: {new_tables}")

        for target in target_tables:
            if target not in post_tables:
                raise RuntimeError(f"Expected table '{target}' was not created!")

        print("=== Migration 003 SUCCESS ===")
        return {
            "ok": True,
            "pre_integrity": pre_integrity,
            "post_integrity": post_integrity,
            "pre_table_count": len(pre_tables),
            "post_table_count": len(post_tables),
            "new_tables": list(new_tables),
            "remaining_tables": post_tables
        }
    finally:
        conn.close()

if __name__ == "__main__":
    db_file = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "storage_vault/nexus_unified.db"
    mig_file = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else "migrations/003_academic_results.sql"
    is_dry = "--dry-run" in sys.argv
    res = run_migration(db_file, mig_file, dry_run=is_dry)
    print(json.dumps(res, indent=2))
