@echo off
setlocal enabledelayedexpansion
title ScholarFlow
echo.
echo  ================================================
echo   ScholarFlow Quick Start
echo  ================================================
echo.

:: ============================================================
:: 0. 加载 .env（必须在所有检查之前，确保 LLM_BACKEND 等已就绪）
:: ============================================================
if exist .env (
    for /f "usebackq tokens=1* delims==" %%a in (`findstr /v "^#" .env ^| findstr "."`) do (
        if not defined %%a set "%%a=%%b"
    )
)

:: 设置 LLM_BACKEND 默认值（.env 中未设置时使用）
if not defined LLM_BACKEND set "LLM_BACKEND=ollama"

:: ============================================================
:: 0b. 自适应检测 Python 路径
::     优先级：venv > conda scholarflow > 系统 python
:: ============================================================
set PYTHON=
:: 1) 项目内 venv
if exist ".\venv\Scripts\python.exe" (
    set "PYTHON=.\venv\Scripts\python.exe"
)
:: 2) conda scholarflow 环境
if not defined PYTHON (
    for /f "tokens=*" %%i in ('where conda 2^>nul') do set CONDA_CMD=%%i
    if defined CONDA_CMD (
        for /f "tokens=1*" %%i in ('conda info --envs 2^>nul ^| findstr scholarflow') do (
            if exist "%%j\python.exe" set "PYTHON=%%j\python.exe"
        )
    )
)
:: 3) 系统 python 兜底
if not defined PYTHON (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON=python"
)
:: 4) 都找不到则报错退出
if not defined PYTHON (
    echo [ERROR] 找不到 Python 环境。请先：
    echo         1. 运行 install_deps.bat 创建 scholarflow conda 环境，或
    echo         2. 手动 conda activate scholarflow
    pause
    exit /b 1
)
echo [OK] Python: !PYTHON!

:: ============================================================
:: 1. 检查 PostgreSQL（Docker）
:: ============================================================
echo  [1/3] Checking database...
docker ps --filter "name=scholarflow-pg" --filter "status=running" --format "{{.Names}}" | findstr scholarflow-pg >nul 2>nul
if !errorlevel! neq 0 (
    echo  Starting PostgreSQL container...
    docker start scholarflow-pg >nul 2>nul
    if !errorlevel! neq 0 (
        echo  Creating PostgreSQL container...
        docker run -d --name scholarflow-pg -p 5433:5432 -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=scholarflow -e POSTGRES_DB=scholarflow postgres:16 >nul 2>nul
    )
    timeout /t 3 >nul
)
echo  [OK] PostgreSQL is running.

:: ============================================================
:: 2. 检查 Ollama（仅当 LLM_BACKEND=ollama 时）
:: ============================================================
if /i "!LLM_BACKEND!"=="ollama" (
    echo  [2/3] Checking Ollama...
    curl -s http://localhost:11434/api/tags >nul 2>nul
    if !errorlevel! neq 0 (
        echo  Starting Ollama...
        start "" ollama serve
        timeout /t 5 >nul
    )
    curl -s http://localhost:11434/api/tags >nul 2>nul
    if !errorlevel! neq 0 (
        echo  [WARN] Ollama 未运行。请手动运行: ollama serve
        echo         或修改 .env 中 LLM_BACKEND=deepseek 切换云端 API
    ) else (
        echo  [OK] Ollama is running.
    )
) else (
    echo  [2/3] LLM backend: !LLM_BACKEND! ^(跳过 Ollama 检查^)
)

:: ============================================================
:: 3. 启动后端 + 打开浏览器
:: ============================================================
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

:: 延迟打开浏览器（给后端 3 秒启动时间）
start "" cmd /c "timeout /t 3 >nul && start http://localhost:8000"

set PYTHONPATH=%CD%
!PYTHON! -m app.main
pause
