@echo off
setlocal
echo ============================================================
echo    NEXUSNODE UNIVERSAL CLI — WINDOWS SETUP
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Installation failed.
    pause
    exit /b %ERRORLEVEL%
)
echo.
pause
