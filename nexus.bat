@echo off
setlocal
python -m nexus %*
exit /b %ERRORLEVEL%
