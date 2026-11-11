@echo off
setlocal
title ScholarFlow offline deployment
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1"
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="0" start "" http://localhost:8000
pause
exit /b %RESULT%
