@echo off
setlocal
set ULVO_EXE=E:\Workspace\Active\ULVO\target\x86_64-pc-windows-gnu\release\ulvo.exe
if exist "%ULVO_EXE%" (
    "%ULVO_EXE%" run "%~dp0." -- python -m nexus %*
    exit /b %ERRORLEVEL%
)
where ulvo >nul 2>nul
if %ERRORLEVEL% equ 0 (
    ulvo run "%~dp0." -- python -m nexus %*
    exit /b %ERRORLEVEL%
)
python -m nexus %*
exit /b %ERRORLEVEL%
