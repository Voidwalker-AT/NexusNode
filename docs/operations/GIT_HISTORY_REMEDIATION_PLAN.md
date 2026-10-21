# NexusNode — Git History Credential Remediation Plan

**Status:** Proposed / Review Required (Zero Automated Rewrites or Force-Pushes Executed)  
**Author:** Google Antigravity (Security-Focused Systems Engineer)  
**Date:** 2026-10-21  

---

## 1. Executive Summary

A comprehensive secret audit of commit `feee2ef98c8df6ab95aa47d75a80565a861264f3` identified historical exposures in the Git commit graph:
1. **Termux SSH Password (`anmol2005`)**: Introduced in commit `02a70c0` and historical test scripts. (Active password on BG6 has already been rotated, Ed25519 key authentication deployed, and all active source occurrences replaced with secure environment/key lookups).
2. **Production PBKDF2 Password Hashes**: Embedded in 5 historical offline test/cracking scripts (`crack_admin_fast.py`, `crack_legacy_admin.py`, etc.). The unsafe files have been removed from the active working tree (`git rm`), and sanitized templates placed in `scripts/archive/`.
3. **Student Institutional PII**: Real student email (`anmol.11794@stu.upes.ac.in`), SAP ID (`590011794`), and Student Unique ID UUID (`3a678d8e-8817-41e6-b1a8-5a3ec6ee4948`) present in historical operational documentation and commit diffs (`ae3ab3c`, `feee2ef`).

Per engineering directives, **Git history has not been rewritten and no force-pushes have been executed.** This document provides the authoritative, safe migration procedure for sanitizing historical commits when operator approval is granted.

---

## 2. Pre-Requisites & Safety Gates

Before any history rewrite is executed:
1. **Production Device Independence**: The production TECNO BG6 appliance is running from its local working copy (`~/server`) independent of GitHub remote commit SHAs.
2. **Full Repository Backup**:
   ```powershell
   git clone --mirror "E:\Workspace\Active\NexusNode\server" "E:\Workspace\Active\NexusNode\server_git_mirror_backup.git"
   ```
3. **Production Database Snapshot**: Confirmed consistent snapshot on BG6 (`storage_vault/backups/nexus_backup_phase1c_stage1_*.db`).

---

## 3. Recommended Remediation Tool: `git-filter-repo`

`git-filter-repo` is the official Git-recommended, high-performance tool for repository sanitization (superior to deprecated `git filter-branch` and safer than BFG).

### Step 1: Install `git-filter-repo`
```powershell
pip install git-filter-repo
```

### Step 2: Define Replacement Expressions File (`expressions.txt`)
```text
anmol2005==>[REDACTED_SSH_PASSWORD]
590011794==>590000000
anmol.11794@stu.upes.ac.in==>student@stu.upes.ac.in
ANMOL.11794@stu.upes.ac.in==>student@stu.upes.ac.in
3a678d8e-8817-41e6-b1a8-5a3ec6ee4948==>00000000-0000-0000-0000-000000000000
pbkdf2_sha256$100000$c985f99e67d2ab8e2de1d1ddfe115225$52c1b3a60d537f84c4e482448181b33c9dfb4727fb80741dddfbe64ee42c1e1c==>pbkdf2_sha256$100000$sanitized_salt$sanitized_digest
e1756a3fc8ad9a40ca179c15372b2dc60aba41500bcb30b44ec437681e897c06==>0000000000000000000000000000000000000000000000000000000000000000
```

### Step 3: Remove Deleted Unsafe Scripts from All Historical Commits
```powershell
git filter-repo --invert-paths `
    --path scripts/check_admin_pass_candidates.py `
    --path scripts/check_user_passwords.py `
    --path scripts/crack_admin_fast.py `
    --path scripts/crack_legacy_admin.py `
    --path scripts/test_passwords.py
```

### Step 4: Scrub Text Occurrences Across All Tree Objects
```powershell
git filter-repo --replace-text expressions.txt
```

### Step 5: Verification of Rewritten History
```powershell
git log --all -S"anmol2005"
git log --all -S"590011794"
git log --all -S"c985f99e67d2ab8e2de1d1ddfe115225"
```
*Expected: 0 commits returned for all queries.*

### Step 6: Upstream Coordination & Remote Push
Because history rewriting alters all commit hashes:
1. Coordinate with collaborators/auditors (Gemini Argon).
2. Push with lease:
   ```powershell
   git push origin --force-with-lease --all
   git push origin --force-with-lease --tags
   ```
3. Update production BG6 local remotes:
   ```bash
   ssh bg6 "cd ~/server && git fetch origin && git reset --soft origin/main"
   ```

---

## 4. Current Status
- **Active Working Tree:** Fully contained & sanitized.
- **Git History:** Intact and preserved until explicit operator approval of this migration plan.
