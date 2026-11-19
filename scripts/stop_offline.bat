@echo off
setlocal
title ScholarFlow - Stop
pushd "%~dp0"
if errorlevel 1 exit /b 1

if not exist "compose.yaml" (
    echo [ERROR] Put stop.bat in the original deployment folder beside compose.yaml.
    goto :failed
)
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop is not running.
    goto :failed
)
docker compose stop
if errorlevel 1 goto :failed
echo.
echo [OK] Services stopped. Your database, documents and models are preserved.
echo Double-click start.bat to start again.
popd
pause
exit /b 0

:failed
echo [ERROR] Stop failed. See the message above.
popd
pause
exit /b 1
