<#
.SYNOPSIS
    NexusNode Universal Remote CLI - Windows Automated Installer
.DESCRIPTION
    Installs nexusnode-cli, creates standard command shims in %LOCALAPPDATA%\NexusNode\bin,
    and automatically registers the directory into Windows User PATH (HKCU\Environment\Path).
    Requires ZERO administrator privileges and ZERO manual PATH editing.
#>

[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

# Paths
$InstallDir = Join-Path $env:LOCALAPPDATA "NexusNode"
$BinDir = Join-Path $InstallDir "bin"

function Broadcast-EnvironmentChange {
    try {
        $signature = @'
[DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, IntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out IntPtr lpdwResult);
'@
        $type = Add-Type -MemberDefinition $signature -Name "Win32Env" -Namespace "NexusNode" -PassThru -ErrorAction SilentlyContinue
        if ($type) {
            $HWND_BROADCAST = [IntPtr]0xFFFF
            $WM_SETTINGCHANGE = 0x001A
            $SMTO_ABORTIFHUNG = 0x0002
            $result = [IntPtr]::Zero
            [NexusNode.Win32Env]::SendMessageTimeout($HWND_BROADCAST, $WM_SETTINGCHANGE, [IntPtr]::Zero, "Environment", $SMTO_ABORTIFHUNG, 5000, [ref]$result) | Out-Null
        }
    } catch {
        # Fallback continues gracefully
    }
}

# ---------------------------------------------------------------------------
# UNINSTALL HANDLER
# ---------------------------------------------------------------------------
if ($Uninstall) {
    Write-Host "`nNexusNode CLI - Windows Uninstaller" -ForegroundColor Yellow
    Write-Host "--------------------------------------------------"

    # 1. Remove from User PATH
    try {
        $UserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
        if ($UserPath) {
            $Entries = $UserPath -split ";" | Where-Object {
                if (-not $_ -or -not $_.Trim()) { return $false }
                $p = $_.Trim()
                return ($p.TrimEnd('\') -ne $BinDir.TrimEnd('\'))
            }
            $NewPath = $Entries -join ";"
            [System.Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
            Broadcast-EnvironmentChange
        }
    } catch {
        Write-Warning "Could not update User PATH in registry: $_"
    }

    # 2. Remove files
    if (Test-Path $InstallDir) {
        Remove-Item -Path $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-Host "[OK] NexusNode CLI removed from system." -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------------------
# INSTALLATION PROCESS
# ---------------------------------------------------------------------------
Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "   NEXUSNODE UNIVERSAL CLI - WINDOWS INSTALLER" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Locate Python
$PythonCmd = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCmd = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCmd = "python"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $PythonCmd = "python3"
}

if (-not $PythonCmd) {
    Write-Error @"
[ERROR] Python 3.8+ was not found on this system.
Please install Python from https://www.python.org/downloads/
Ensure Python is installed, then re-run this installer.
"@
    exit 1
}

Write-Host "`n[1/4] Checking Python environment ($PythonCmd)..." -ForegroundColor Yellow
$pyVer = & $PythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
Write-Host "      Detected Python: $pyVer" -ForegroundColor Green

# 2. Install / Upgrade nexusnode-cli via pip
Write-Host "`n[2/4] Installing / Upgrading nexusnode-cli package from PyPI..." -ForegroundColor Yellow
& $PythonCmd -m pip install --upgrade --no-warn-script-location nexusnode-cli
if ($LASTEXITCODE -ne 0) {
    Write-Error "[ERROR] Failed to install nexusnode-cli from PyPI."
    exit 1
}

# 3. Create %LOCALAPPDATA%\NexusNode\bin and Shims
Write-Host "`n[3/4] Creating universal executable shims in $BinDir..." -ForegroundColor Yellow
if (-not (Test-Path $BinDir)) {
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
}

# nexus.cmd (For Command Prompt and standard Windows PATH execution)
$cmdContent = @'
@echo off
setlocal
where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    py -m nexus %*
    exit /b %ERRORLEVEL%
)
where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python -m nexus %*
    exit /b %ERRORLEVEL%
)
echo [ERROR] Python was not found. Please install Python 3.8+ from https://python.org
exit /b 1
'@
Set-Content -Path (Join-Path $BinDir "nexus.cmd") -Value $cmdContent -Force -Encoding ASCII

# nexus.bat
Set-Content -Path (Join-Path $BinDir "nexus.bat") -Value $cmdContent -Force -Encoding ASCII

# nexus.ps1 (For native PowerShell - transparent forwarding without CmdletBinding parameter restrictions)
$ps1Content = @'
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { $null }
if ($py) {
    & $py -m nexus @args
    exit $LASTEXITCODE
} else {
    Write-Error "[ERROR] Python was not found. Please install Python 3.8+ from https://python.org"
    exit 1
}
'@
Set-Content -Path (Join-Path $BinDir "nexus.ps1") -Value $ps1Content -Force -Encoding ASCII

# nexus (Bash script for Git Bash / MSYS2 / WSL)
$shContent = @'
#!/usr/bin/env sh
if command -v py >/dev/null 2>&1; then
    exec py -m nexus "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 -m nexus "$@"
elif command -v python >/dev/null 2>&1; then
    exec python -m nexus "$@"
else
    echo "[ERROR] Python was not found. Please install Python 3.8+." >&2
    exit 1
fi
'@
Set-Content -Path (Join-Path $BinDir "nexus") -Value $shContent -Force -Encoding ASCII

# 4. Register %LOCALAPPDATA%\NexusNode\bin in Windows User PATH
Write-Host "`n[4/4] Registering $BinDir into Windows User PATH..." -ForegroundColor Yellow
$UserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
$CurrentEntries = @()
if ($UserPath) {
    $CurrentEntries = $UserPath -split ";" | Where-Object { $_ -and $_.Trim() }
}

$NormBin = $BinDir.TrimEnd('\')
$Exists = $false
foreach ($entry in $CurrentEntries) {
    if ($entry -and $entry.Trim().TrimEnd('\') -ieq $NormBin) {
        $Exists = $true
        break
    }
}

if (-not $Exists) {
    $NewUserPath = if ($UserPath) { "$UserPath;$BinDir" } else { $BinDir }
    [System.Environment]::SetEnvironmentVariable("Path", $NewUserPath, "User")
    Broadcast-EnvironmentChange
    Write-Host "      [OK] Added '$BinDir' to User PATH." -ForegroundColor Green
} else {
    Write-Host "      [OK] '$BinDir' is already configured in User PATH." -ForegroundColor Green
}

# Update current process PATH for immediate verification
$env:Path = "$BinDir;$env:Path"

# 5. Verification
Write-Host "`nVerifying installation..." -ForegroundColor Yellow
$installedVer = & $PythonCmd -m nexus --version
Write-Host "      $installedVer" -ForegroundColor Green

Write-Host @"

============================================================
   INSTALLATION COMPLETE!
============================================================

You can now open a new PowerShell or Command Prompt window and run:

    nexus connect https://PUBLIC-NEXUSNODE-URL

To check CLI version:
    nexus --version

To see available commands:
    nexus --help

To uninstall in the future:
    powershell -File "$PSScriptRoot\install.ps1" -Uninstall

============================================================
"@ -ForegroundColor Cyan
