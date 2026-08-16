import sys
import os
import subprocess
import venv
import zipfile
import tempfile
import urllib.request
import urllib.error
import shutil
import glob
from pathlib import Path

def print_step(msg):
    print(f"\n[{'-' * 10}] {msg} [{'-' * 10}]")

def check_pypi_name(package_name="nexusnode-cli"):
    print_step(f"Checking PyPI name availability for '{package_name}'")
    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        urllib.request.urlopen(url)
        print(f"INFO: Package name '{package_name}' is already taken on PyPI.")
        return False
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"PASS: Package name '{package_name}' is available on PyPI.")
            return True
        print(f"WARN: Error checking PyPI ({e.code}). Assuming unavailable.")
        return False
    except Exception as e:
        print(f"WARN: Error checking PyPI ({e}).")
        return False

def build_package(repo_root):
    print_step("Building sdist and wheel")
    result = subprocess.run([sys.executable, "-m", "build"], cwd=repo_root, capture_output=True, text=True)
    if result.returncode != 0:
        print("FAIL: Build failed.")
        print(result.stdout)
        print(result.stderr)
        return False
    print("PASS: Build succeeded.")
    return True

def inspect_wheel(repo_root):
    print_step("Inspecting wheel contents")
    dist_dir = os.path.join(repo_root, "dist")
    wheels = glob.glob(os.path.join(dist_dir, "*.whl"))
    if not wheels:
        print("FAIL: No wheel found in dist/.")
        return False, None
    wheel_path = wheels[0]
    
    server_leakage = False
    with zipfile.ZipFile(wheel_path, 'r') as z:
        namelist = z.namelist()
        for name in namelist:
            # Check for server files leaking in
            if name.startswith("app.py") or name.startswith("nexus/app.py"):
                print(f"FAIL: Server file leaked: {name}")
                server_leakage = True
            if name.startswith("nexus_shell_server"):
                print(f"FAIL: Server file leaked: {name}")
                server_leakage = True
            if "resource_governor.py" in name:
                print(f"FAIL: Server file leaked: {name}")
                server_leakage = True
    
    if server_leakage:
        print("FAIL: Wheel contains server files.")
        return False, wheel_path
    
    print("PASS: Wheel contents look clean.")
    return True, wheel_path

def verify_in_venv(wheel_path):
    print_step("Verifying wheel in temporary venv")
    temp_dir = tempfile.mkdtemp(prefix="nexus_venv_")
    try:
        print(f"Creating venv in {temp_dir}")
        venv.create(temp_dir, with_pip=True)
        
        if sys.platform == "win32":
            python_exe = os.path.join(temp_dir, "Scripts", "python.exe")
        else:
            python_exe = os.path.join(temp_dir, "bin", "python")
            
        print("Installing wheel...")
        result = subprocess.run([python_exe, "-m", "pip", "install", wheel_path], capture_output=True, text=True)
        if result.returncode != 0:
            print("FAIL: Wheel installation failed.")
            print(result.stdout)
            print(result.stderr)
            return False
            
        print("Running 'nexus --version'...")
        result = subprocess.run([python_exe, "-m", "nexus", "--version"], capture_output=True, text=True)
        if result.returncode != 0 or "NexusNode CLI" not in result.stdout:
            print("FAIL: 'nexus --version' failed.")
            print(result.stdout)
            print(result.stderr)
            return False
            
        print("Running 'nexus --help'...")
        result = subprocess.run([python_exe, "-m", "nexus", "--help"], capture_output=True, text=True)
        if result.returncode != 0 or "connect" not in result.stdout:
            print("FAIL: 'nexus --help' failed.")
            print(result.stdout)
            print(result.stderr)
            return False
            
        print("PASS: Virtual environment verification succeeded.")
        return True
    finally:
        print(f"Cleaning up venv at {temp_dir}")
        shutil.rmtree(temp_dir, ignore_errors=True)

def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    check_pypi_name()
    
    if not build_package(repo_root):
        sys.exit(1)
        
    wheel_ok, wheel_path = inspect_wheel(repo_root)
    if not wheel_ok:
        sys.exit(1)
        
    if not verify_in_venv(wheel_path):
        sys.exit(1)
        
    print_step("SUMMARY REPORT")
    print("PASS: All checks passed!")
    print("The nexusnode-cli package is ready for distribution.")
    sys.exit(0)

if __name__ == "__main__":
    main()
