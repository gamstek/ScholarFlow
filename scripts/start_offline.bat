@echo off
setlocal
title ScholarFlow - Start
pushd "%~dp0"
if errorlevel 1 exit /b 1

if not exist "compose.yaml" (
    echo [ERROR] Put start.bat in the original deployment folder beside compose.yaml.
    goto :failed
)
if not exist ".env" (
    echo [ERROR] Configure .env and run deploy.bat before starting for the first time.
    goto :failed
)
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Start Docker Desktop first, then try again.
    goto :failed
)
docker compose up -d --pull never
if errorlevel 1 goto :failed
echo.
echo [OK] Services started. Wait a few seconds, then refresh the browser if needed.
start "" http://localhost:8000
popd
pause
exit /b 0

:failed
echo [ERROR] Startup failed. See the message above.
popd
pause
exit /b 1
