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
:: Load .env if exists (仅设置尚未定义的变量，不覆盖已有值)
if exist .env (
    for /f "usebackq tokens=1* delims==" %%a in (`findstr /v "^#" .env ^| findstr "."`) do (
        if not defined %%a set "%%a=%%b"
    )
)

:: 自动检测 scholarflow conda 环境的 Python 路径
:: conda info --envs 输出格式: "scholarflow              C:\Users\...\scholarflow"
:: tokens=1* 按空格分割：%%i = 环境名, %%j = 路径（支持含空格的路径）
set PYTHON=
for /f "tokens=*" %%i in ('where conda 2^>nul') do set CONDA_CMD=%%i
if defined CONDA_CMD (
    for /f "tokens=1*" %%i in ('conda info --envs 2^>nul ^| findstr scholarflow') do (
        if exist "%%j\python.exe" set "PYTHON=%%j\python.exe"
    )
)
:: 兜底：如果 conda 环境已激活，直接用当前 python
if not defined PYTHON (
    where python >nul 2>nul
    if not errorlevel 1 (
        set PYTHON=python
    )
)
if not defined PYTHON (
    echo [ERROR] 找不到 scholarflow 环境的 Python。请先运行: conda activate scholarflow
    pause
    exit /b 1
)
echo [OK] Python: %PYTHON%

set PYTHONPATH=%CD%
%PYTHON% -m app.main
pause
