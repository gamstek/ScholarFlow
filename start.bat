@echo off
title ScholarFlow
echo.
echo  ================================================
echo   ScholarFlow Quick Start
echo  ================================================
echo.

:: 1. Check PostgreSQL (Docker)
echo  [1/3] Checking database...
docker ps --filter "name=scholarflow-pg" --filter "status=running" --format "{{.Names}}" | findstr scholarflow-pg >nul 2>nul
if %errorlevel% neq 0 (
    echo  Starting PostgreSQL container...
    docker start scholarflow-pg >nul 2>nul
    if %errorlevel% neq 0 (
        echo  Creating PostgreSQL container...
        docker run -d --name scholarflow-pg -p 5433:5432 -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=scholarflow -e POSTGRES_DB=scholarflow postgres:16 >nul 2>nul
    )
    timeout /t 3 >nul
)
echo  [OK] PostgreSQL is running.

:: 2. Check Ollama
echo  [2/3] Checking Ollama...
curl -s http://localhost:11434/api/tags >nul 2>nul
if %errorlevel% neq 0 (
    echo  Starting Ollama...
    start "" ollama serve
    timeout /t 5 >nul
)
curl -s http://localhost:11434/api/tags >nul 2>nul
if %errorlevel% neq 0 (
    echo  [ERROR] Ollama is not running. Please run: ollama serve
    pause
    exit /b 1
)
echo  [OK] Ollama is running.

:: 3. Start backend + open browser
echo  [3/3] Starting ScholarFlow...
echo.
echo  ================================================
echo   ScholarFlow is running!
echo   Browser will open automatically...
echo   URL: http://localhost:8000
echo.
echo   Press Ctrl+C to stop.
echo  ================================================
echo.

:: Open browser after 3 seconds
start "" cmd /c "timeout /t 3 >nul && start http://localhost:8000"

:: Start backend
:: 离线模式：跳过 HuggingFace Hub 联网验证，直接从本地缓存加载模型
set HF_HUB_OFFLINE=1
:: Load .env if exists (for DATABASE_URL etc.)
if exist .env (
    for /f "usebackq tokens=1* delims==" %%a in (`findstr /v "^#" .env ^| findstr "."`) do (
        set "%%a=%%b"
    )
)
set PYTHON=C:\Users\HP\.conda\envs\scholarflow\python.exe
set PYTHONPATH=%CD%
%PYTHON% -m app.main
pause
