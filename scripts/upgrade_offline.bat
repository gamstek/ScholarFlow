@echo off
setlocal
title ScholarFlow - Upgrade existing installation
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0upgrade.ps1" %*
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
