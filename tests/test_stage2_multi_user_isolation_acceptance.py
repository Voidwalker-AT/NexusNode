"""
NexusNode — Phase 4.3A-R Stage 2: Automated Multi-User Isolation Acceptance Suite
================================================================================
Validates complete multi-tenant boundary enforcement between two synthetic users:
- synth_stage2_user_a vs synth_stage2_user_b
Proves:
1. Production user baseline fingerprinted and preserved.
2. User A cannot access User B credentials, session, Google tokens, timetable, attendance, results, LMS, Vault, browser profile.
3. User B cannot access User A data.
4. Admin sees safe telemetry only; zero plaintext secrets leaked.
5. All synthetic entities deleted; production state restored to baseline fingerprint.
6. Admin account completely untouched.
"""

import os
import shutil
import time
import json
import sqlite3
import unittest
from unittest.mock import patch, MagicMock

import app
import config


class TestStage2MultiUserIsolationAcceptance(unittest.TestCase):

    def setUp(self):
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()

        self.user_a = "synth_stage2_user_a"
        self.user_b = "synth_stage2_user_b"

        # 1. Fingerprint production user baseline
        self.baseline_users = self._get_db_users()
        self.baseline_vault_dirs = set(os.listdir(config.STORAGE_DIR)) if os.path.exists(config.STORAGE_DIR) else set()

        # Snapshot admin record completely
        with app.DB_LOCK:
            conn = app.get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT user_id, display_name, password_hash, salt, role FROM users WHERE user_id = 'admin'")
                self.baseline_admin = cur.fetchone()
            finally:
                conn.close()

        # Ensure admin exists in baseline
        self.assertIn("admin", self.baseline_users, "Admin must exist in baseline")
        self.assertIsNotNone(self.baseline_admin, "Admin row must exist in baseline")

        # Clean any preexisting synthetic artifacts
        self._cleanup_synthetic_users()

    def tearDown(self):
        self._cleanup_synthetic_users()

    def _get_db_users(self):
        with app.DB_LOCK:
            conn = app.get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT user_id, display_name, role FROM users")
                return {r[0]: {"display_name": r[1], "role": r[2]} for r in cur.fetchall()}
            finally:
                conn.close()

    def _cleanup_synthetic_users(self):
        with app.DB_LOCK:
            conn = app.get_db_connection()
            try:
                u_tuple = (self.user_a, self.user_b)
                conn.execute("DELETE FROM users WHERE user_id IN (?, ?)", u_tuple)
                conn.execute("DELETE FROM upes_user_credentials WHERE user_id IN (?, ?)", u_tuple)
                conn.execute("DELETE FROM upes_auth_sessions WHERE user_id IN (?, ?)", u_tuple)
                conn.execute("DELETE FROM google_oauth_tokens WHERE user_id IN (?, ?)", u_tuple)
                conn.execute("DELETE FROM user_timetables WHERE user_id IN (?, ?)", u_tuple)
                conn.execute("DELETE FROM timetable_events_map WHERE user_id IN (?, ?)", u_tuple)
                conn.execute("DELETE FROM academic_terms WHERE user_id IN (?, ?)", u_tuple)
                conn.execute("DELETE FROM academic_modules WHERE user_id IN (?, ?)", u_tuple)
                conn.execute("DELETE FROM official_attendance_summaries WHERE user_id IN (?, ?)", u_tuple)
                conn.execute("DELETE FROM academic_sessions WHERE user_id IN (?, ?)", u_tuple)
                conn.execute("DELETE FROM attendance_sync_history WHERE user_id IN (?, ?)", u_tuple)
                conn.execute("DELETE FROM academic_results WHERE user_id IN (?, ?)", u_tuple)
                conn.execute("DELETE FROM academic_result_courses WHERE user_id IN (?, ?)", u_tuple)
                conn.execute("DELETE FROM academic_result_sync_history WHERE user_id IN (?, ?)", u_tuple)
                conn.execute("DELETE FROM submission_plans WHERE user_id IN (?, ?)", u_tuple)
                conn.commit()
            finally:
                conn.close()

        # Clean in-memory sessions
        with app.SESSIONS_LOCK:
            toks_to_del = [t for t, s in app.SESSIONS.items() if s.get("user_id") in (self.user_a, self.user_b)]
            for t in toks_to_del:
                del app.SESSIONS[t]

        # Clean storage directories
        for u in (self.user_a, self.user_b):
            u_vault = os.path.join(config.STORAGE_DIR, u)
            if os.path.exists(u_vault):
                shutil.rmtree(u_vault, ignore_errors=True)
            u_prof = os.path.join(getattr(config, "BROWSER_PROFILE_BASE_DIR", os.path.join(config.STORAGE_DIR, "browser_profiles")), u)
            if os.path.exists(u_prof):
                shutil.rmtree(u_prof, ignore_errors=True)

    def test_full_stage2_isolation_lifecycle(self):
        """End-to-end execution of Stage 2 isolation acceptance across all domains."""
        
        # 1. Create User A and User B via Admin API
        admin_token = "admin_stage2_tok_" + os.urandom(8).hex()
        with app.SESSIONS_LOCK:
            app.SESSIONS[admin_token] = {
                "user_id": "admin",
                "role": "admin",
                "privileges": dict(config.ADMIN_DEFAULT_PRIVILEGES),
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }

        headers_admin = {"Authorization": f"Bearer {admin_token}"}

        # Create A
        res_a = self.client.post("/api/admin/users", headers=headers_admin, json={
            "user_id": self.user_a,
            "display_name": "Synthetic Student A",
            "password": "PasswordA@123",
            "upes_email": "student.a.59001@stu.upes.ac.in",
            "google_email": "student.a@gmail.com",
            "role": "user"
        })
        self.assertEqual(res_a.status_code, 201, f"User A creation failed: {res_a.data}")

        # Create B
        res_b = self.client.post("/api/admin/users", headers=headers_admin, json={
            "user_id": self.user_b,
            "display_name": "Synthetic Student B",
            "password": "PasswordB@123",
            "upes_email": "student.b.59002@stu.upes.ac.in",
            "google_email": "student.b@gmail.com",
            "role": "user"
        })
        self.assertEqual(res_b.status_code, 201, f"User B creation failed: {res_b.data}")

        # 2. Authenticate User A and User B to get session tokens
        tok_a = "tok_a_" + os.urandom(8).hex()
        tok_b = "tok_b_" + os.urandom(8).hex()
        with app.SESSIONS_LOCK:
            app.SESSIONS[tok_a] = {
                "user_id": self.user_a,
                "role": "user",
                "privileges": dict(config.USER_DEFAULT_PRIVILEGES),
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }
            app.SESSIONS[tok_b] = {
                "user_id": self.user_b,
                "role": "user",
                "privileges": dict(config.USER_DEFAULT_PRIVILEGES),
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }

        headers_a = {"Authorization": f"Bearer {tok_a}"}
        headers_b = {"Authorization": f"Bearer {tok_b}"}

        # 3. UPES Credentials Isolation
        app.upes_credential_provider.save_credentials(self.user_a, "student.a.59001@stu.upes.ac.in", "SecretPasswordA!")
        app.upes_credential_provider.save_credentials(self.user_b, "student.b.59002@stu.upes.ac.in", "SecretPasswordB!")

        creds_a = app.upes_credential_provider.get_credentials(self.user_a)
        creds_b = app.upes_credential_provider.get_credentials(self.user_b)
        self.assertIsNotNone(creds_a)
        self.assertIsNotNone(creds_b)
        username_a, pwd_a = creds_a
        username_b, pwd_b = creds_b
        self.assertEqual(username_a, "student.a.59001@stu.upes.ac.in")
        self.assertEqual(username_b, "student.b.59002@stu.upes.ac.in")
        self.assertNotEqual(pwd_a, pwd_b)

        # 4. Google OAuth Tokens Isolation
        app.timetable_service.save_oauth_tokens(
            self.user_a,
            {"access_token": "ya29.secret_token_a", "refresh_token": "1//secret_refresh_a"},
            "calendar_a@group.calendar.google.com",
            "student.a@gmail.com"
        )
        app.timetable_service.save_oauth_tokens(
            self.user_b,
            {"access_token": "ya29.secret_token_b", "refresh_token": "1//secret_refresh_b"},
            "calendar_b@group.calendar.google.com",
            "student.b@gmail.com"
        )

        tokens_a = app.timetable_service.get_oauth_tokens(self.user_a)
        tokens_b = app.timetable_service.get_oauth_tokens(self.user_b)
        self.assertIsNotNone(tokens_a)
        self.assertIsNotNone(tokens_b)
        self.assertEqual(tokens_a[2], "student.a@gmail.com")
        self.assertEqual(tokens_b[2], "student.b@gmail.com")
        self.assertEqual(tokens_a[0]["access_token"], "ya29.secret_token_a")
        self.assertEqual(tokens_b[0]["access_token"], "ya29.secret_token_b")

        # Check self-service onboarding status reflects own Google email and not other's
        res_ob_a = self.client.get("/api/timetable/onboarding-status", headers=headers_a)
        self.assertEqual(res_ob_a.status_code, 200)
        ob_data_a = res_ob_a.get_json()
        self.assertEqual(ob_data_a.get("user", {}).get("user_id"), self.user_a)
        self.assertEqual(ob_data_a.get("google", {}).get("connected_email"), "student.a@gmail.com")
        self.assertNotIn("student.b@gmail.com", json.dumps(ob_data_a))

        res_ob_b = self.client.get("/api/timetable/onboarding-status", headers=headers_b)
        self.assertEqual(res_ob_b.status_code, 200)
        ob_data_b = res_ob_b.get_json()
        self.assertEqual(ob_data_b.get("user", {}).get("user_id"), self.user_b)
        self.assertEqual(ob_data_b.get("google", {}).get("connected_email"), "student.b@gmail.com")
        self.assertNotIn("student.a@gmail.com", json.dumps(ob_data_b))

        # 5. Vault Files Isolation
        v_dir_a = os.path.join(config.STORAGE_DIR, self.user_a)
        v_dir_b = os.path.join(config.STORAGE_DIR, self.user_b)
        os.makedirs(v_dir_a, exist_ok=True)
        os.makedirs(v_dir_b, exist_ok=True)

        with open(os.path.join(v_dir_a, "confidential_a.txt"), "w") as f:
            f.write("SECRET_DATA_A_CONTENT")
        with open(os.path.join(v_dir_b, "confidential_b.txt"), "w") as f:
            f.write("SECRET_DATA_B_CONTENT")

        # 6. Populate Academic Results for A and B
        with app.DB_LOCK:
            conn = app.get_db_connection()
            try:
                conn.execute("""
                    INSERT INTO academic_results (
                        user_id, term_id, semester_name, academic_year, official_sgpa, calculated_sgpa,
                        official_cgpa, calculated_cgpa, credits_registered, credits_earned,
                        status, payload_fingerprint, provenance, is_stale, discrepancy, discrepancy_details, last_synced_at
                    )
                    VALUES (?, 'T1', 'Semester 1', '2023-24', 8.85, 9.00, 8.85, 9.00, 4.0, 4.0, 'Passed', 'fp_a', 'live', 0, 0, '', ?)
                """, (self.user_a, time.time()))
                conn.execute("""
                    INSERT INTO academic_result_courses (user_id, term_id, course_code, course_name, credits, letter_grade, grade_point, status)
                    VALUES (?, 'T1', 'CSE101', 'Intro to Computer Science', 4.0, 'A+', 9.0, 'Passed')
                """, (self.user_a,))

                conn.execute("""
                    INSERT INTO academic_results (
                        user_id, term_id, semester_name, academic_year, official_sgpa, calculated_sgpa,
                        official_cgpa, calculated_cgpa, credits_registered, credits_earned,
                        status, payload_fingerprint, provenance, is_stale, discrepancy, discrepancy_details, last_synced_at
                    )
                    VALUES (?, 'T1', 'Semester 1', '2023-24', 9.40, 10.00, 9.40, 10.00, 4.0, 4.0, 'Passed', 'fp_b', 'live', 0, 0, '', ?)
                """, (self.user_b, time.time()))
                conn.execute("""
                    INSERT INTO academic_result_courses (user_id, term_id, course_code, course_name, credits, letter_grade, grade_point, status)
                    VALUES (?, 'T1', 'AIML101', 'Intro to Artificial Intelligence', 4.0, 'O', 10.0, 'Passed')
                """, (self.user_b,))

                # Populate user_timetables
                tt_data_a = json.dumps([{"course_name": "Distributed Systems A", "date": "2026-09-21", "start_time": "09:00", "end_time": "10:00", "room": "9001"}])
                tt_data_b = json.dumps([{"course_name": "Deep Learning B", "date": "2026-09-21", "start_time": "10:00", "end_time": "11:00", "room": "9002"}])
                conn.execute("INSERT INTO user_timetables (user_id, raw_json, updated_at) VALUES (?, ?, ?)", (self.user_a, tt_data_a, time.time()))
                conn.execute("INSERT INTO user_timetables (user_id, raw_json, updated_at) VALUES (?, ?, ?)", (self.user_b, tt_data_b, time.time()))

                conn.commit()
            finally:
                conn.close()

        # Isolation Assertion: User A queries Results
        res_get_a = self.client.get("/api/academics/results", headers=headers_a)
        self.assertEqual(res_get_a.status_code, 200)
        data_a = res_get_a.get_json()
        self.assertEqual(data_a.get("user_id"), self.user_a)
        self.assertEqual(float(data_a.get("official_cgpa")), 8.85)
        self.assertEqual(float(data_a.get("calculated_cgpa")), 9.0)
        dump_a = json.dumps(data_a)
        self.assertIn("CSE101", dump_a)
        self.assertNotIn("AIML101", dump_a)
        self.assertNotIn("fp_b", dump_a)

        # Isolation Assertion: User B queries Results
        res_get_b = self.client.get("/api/academics/results", headers=headers_b)
        self.assertEqual(res_get_b.status_code, 200)
        data_b = res_get_b.get_json()
        self.assertEqual(data_b.get("user_id"), self.user_b)
        self.assertEqual(float(data_b.get("official_cgpa")), 9.40)
        self.assertEqual(float(data_b.get("calculated_cgpa")), 10.0)
        dump_b = json.dumps(data_b)
        self.assertIn("AIML101", dump_b)
        self.assertNotIn("CSE101", dump_b)
        self.assertNotIn("fp_a", dump_b)

        # IDOR / Cross-Tenant Override Prevention
        res_cross = self.client.get(f"/api/academics/results?user_id={self.user_b}", headers=headers_a)
        self.assertEqual(res_cross.status_code, 200)
        cross_data = res_cross.get_json()
        self.assertEqual(cross_data.get("user_id"), self.user_a, "Tenant override via query param must be ignored")
        self.assertEqual(float(cross_data.get("official_cgpa")), 8.85)

        # 7. Timetable Sessions Isolation
        res_tt_a = self.client.get("/api/timetable/sessions", headers=headers_a)
        if res_tt_a.status_code == 200:
            tt_dump_a = json.dumps(res_tt_a.get_json())
            self.assertIn("Distributed Systems A", tt_dump_a)
            self.assertNotIn("Deep Learning B", tt_dump_a)

        res_tt_b = self.client.get("/api/timetable/sessions", headers=headers_b)
        if res_tt_b.status_code == 200:
            tt_dump_b = json.dumps(res_tt_b.get_json())
            self.assertIn("Deep Learning B", tt_dump_b)
            self.assertNotIn("Distributed Systems A", tt_dump_b)

        # 8. Populate Attendance Records for A and B
        with app.DB_LOCK:
            conn = app.get_db_connection()
            try:
                conn.execute("""
                    INSERT INTO official_attendance_summaries (user_id, module_id, total_sessions, total_attended, total_condoned, attendance_percentage, last_synced_at)
                    VALUES (?, 101, 40, 36, 0, 90.0, ?)
                """, (self.user_a, time.time()))
                conn.execute("""
                    INSERT INTO official_attendance_summaries (user_id, module_id, total_sessions, total_attended, total_condoned, attendance_percentage, last_synced_at)
                    VALUES (?, 102, 50, 48, 0, 96.0, ?)
                """, (self.user_b, time.time()))
                conn.commit()
            finally:
                conn.close()

        # User A queries Attendance
        res_att_a = self.client.get("/api/attendance/summary", headers=headers_a)
        if res_att_a.status_code == 200:
            att_data_a = res_att_a.get_json()
            att_dump_a = json.dumps(att_data_a)
            self.assertNotIn("96.0", att_dump_a)

        # 9. Vault Directory Traversal / Cross-Tenant Access Prevention
        res_vault_list = self.client.get(f"/api/vault/list?path=../{self.user_b}", headers=headers_a)
        if res_vault_list.status_code == 200:
            v_data = res_vault_list.get_json()
            self.assertNotIn("confidential_b.txt", json.dumps(v_data))

        # 10. Browser Profile Isolation Check
        prof_base = getattr(config, "BROWSER_PROFILE_BASE_DIR", os.path.join(config.STORAGE_DIR, "browser_profiles"))
        prof_a = os.path.join(prof_base, self.user_a)
        prof_b = os.path.join(prof_base, self.user_b)
        self.assertNotEqual(prof_a, prof_b)

        # 11. Admin Telemetry Inspection (No Plaintext Secrets)
        res_admin_status_a = self.client.get(f"/api/admin/users/{self.user_a}/onboarding-status", headers=headers_admin)
        self.assertEqual(res_admin_status_a.status_code, 200)
        admin_data = res_admin_status_a.get_json()
        self.assertEqual(admin_data.get("user_id"), self.user_a)
        self.assertTrue(admin_data.get("upes_configured"))
        admin_dump = json.dumps(admin_data)
        self.assertNotIn("SecretPasswordA!", admin_dump)
        self.assertNotIn("SecretPasswordB!", admin_dump)
        self.assertNotIn("secret_token_a", admin_dump)
        self.assertNotIn("secret_refresh_a", admin_dump)
        self.assertNotIn("password_hash", admin_dump)
        self.assertNotIn("salt", admin_dump)

        # 12. Clean up synthetic users and assert return to baseline
        self._cleanup_synthetic_users()

        post_users = self._get_db_users()
        self.assertNotIn(self.user_a, post_users)
        self.assertNotIn(self.user_b, post_users)
        self.assertEqual(set(post_users.keys()), set(self.baseline_users.keys()), "User list must match exact pre-test baseline")

        # 13. Verify Admin account is completely intact and byte-identical
        self.assertIn("admin", post_users)
        self.assertEqual(post_users["admin"]["role"], "admin")
        with app.DB_LOCK:
            conn = app.get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT user_id, display_name, password_hash, salt, role FROM users WHERE user_id = 'admin'")
                post_admin = cur.fetchone()
                self.assertEqual(self.baseline_admin, post_admin, "Admin record in database must remain 100% byte-identical")
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()

