"""
NexusNode Phase 4.2B - Per-File Test Suite Recount & Execution
Runs each test file in tests/ with python -m pytest,
recording exact:
- test file name
- tests collected
- tests passed
- tests failed
- tests skipped
- execution duration
"""
import subprocess
import json
import time
import os
import sys

def run_test_file(test_file):
    cmd = [sys.executable, "-m", "pytest", f"tests/{test_file}", "-q", "--tb=short"]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    duration = time.time() - t0
    
    out = proc.stdout
    err = proc.stderr
    
    # Parse pytest summary line
    # e.g.: "12 passed in 1.45s" or "5 passed, 1 skipped in 0.50s"
    summary_line = ""
    for line in out.split("\n"):
        if "passed" in line or "failed" in line or "error" in line or "skipped" in line:
            summary_line = line.strip()
            
    passed = 0
    failed = 0
    skipped = 0
    errors = 0
    
    import re
    p_match = re.search(r"(\d+)\s+passed", summary_line)
    if p_match: passed = int(p_match.group(1))
    
    f_match = re.search(r"(\d+)\s+failed", summary_line)
    if f_match: failed = int(f_match.group(1))
    
    s_match = re.search(r"(\d+)\s+skipped", summary_line)
    if s_match: skipped = int(s_match.group(1))
    
    e_match = re.search(r"(\d+)\s+error", summary_line)
    if e_match: errors = int(e_match.group(1))
    
    collected = passed + failed + skipped + errors

    return {
        "file": test_file,
        "collected": collected,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errors": errors,
        "duration_sec": round(duration, 3),
        "exit_code": proc.returncode,
        "summary": summary_line,
        "stdout_tail": out.strip()[-300:] if out else "",
        "stderr_tail": err.strip()[-300:] if err else ""
    }

def main():
    test_files = [f for f in sorted(os.listdir("tests")) if f.startswith("test_") and f.endswith(".py")]
    print(f"Discovered {len(test_files)} test files in tests/")
    
    results = []
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    total_errors = 0
    total_collected = 0
    total_duration = 0
    
    for f in test_files:
        print(f"Running {f}...", end="", flush=True)
        res = run_test_file(f)
        results.append(res)
        total_passed += res["passed"]
        total_failed += res["failed"]
        total_skipped += res["skipped"]
        total_errors += res["errors"]
        total_collected += res["collected"]
        total_duration += res["duration_sec"]
        
        status_str = f"P:{res['passed']} F:{res['failed']} S:{res['skipped']} E:{res['errors']} ({res['duration_sec']}s)"
        print(f" -> {status_str}")

    summary = {
        "total_files": len(test_files),
        "total_collected": total_collected,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "total_skipped": total_skipped,
        "total_errors": total_errors,
        "total_duration_sec": round(total_duration, 2),
        "files": results
    }

    with open("scripts/test_execution_report.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n==================================================")
    print("TEST SUITE EXECUTION COMPLETE")
    print(f"Files: {len(test_files)}")
    print(f"Collected: {total_collected}")
    print(f"Passed: {total_passed}")
    print(f"Failed: {total_failed}")
    print(f"Skipped: {total_skipped}")
    print(f"Errors: {total_errors}")
    print(f"Total Duration: {round(total_duration, 2)}s")
    print("==================================================")

if __name__ == "__main__":
    main()
