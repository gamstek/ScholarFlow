@echo off
setlocal enabledelayedexpansion
title ScholarFlow — GPU 依赖智能安装

echo.
echo  ================================================
echo   ScholarFlow — GPU 依赖智能安装
echo  ================================================
echo.

:: ─── 1. 检测 conda 环境 ────────────────────────────
set "CONDA_ENV="
where conda >nul 2>nul
if %errorlevel% equ 0 (
    for /f "tokens=*" %%i in ('conda info --envs 2^>nul ^| findstr /r /c:"\*"') do (
        set "LINE=%%i"
        for /f "tokens=1" %%j in ("!LINE!") do set "CONDA_ENV=%%j"
    )
    if "!CONDA_ENV!"=="" set "CONDA_ENV=base"
    echo  [INFO] 检测到 conda 环境: !CONDA_ENV!
) else (
    echo  [INFO] 未检测到 conda，使用系统 Python
)

:: ─── 2. 检测 GPU 型号 ──────────────────────────────
set "GPU_NAME="
where nvidia-smi >nul 2>nul
if %errorlevel% neq 0 (
    echo  [ERROR] 未找到 nvidia-smi，请确认 NVIDIA 驱动已安装
    pause
    exit /b 1
)

for /f "tokens=* skip=1" %%i in ('nvidia-smi --query-gpu=name --format=csv,noheader 2^>nul') do (
    set "GPU_NAME=%%i"
    goto :gpu_found
)
:gpu_found

if "!GPU_NAME!"=="" (
    echo  [ERROR] 无法检测到 NVIDIA GPU
    pause
    exit /b 1
)
echo  [INFO] 检测到 GPU: !GPU_NAME!

:: ─── 3. 判断 GPU 系列并选择依赖文件 ────────────────
set "REQ_FILE="
set "GPU_SERIES="

echo !GPU_NAME! | findstr /i "RTX 50" >nul
if !errorlevel! equ 0 (
    set "REQ_FILE=requirements\requirements-rtx50.txt"
    set "GPU_SERIES=RTX 50 系列 (Blackwell)"
    goto :selected
)

echo !GPU_NAME! | findstr /i "RTX 40" >nul
if !errorlevel! equ 0 (
    set "REQ_FILE=requirements\requirements-rtx40.txt"
    set "GPU_SERIES=RTX 40 系列 (Ada Lovelace)"
    goto :selected
)

echo !GPU_NAME! | findstr /i "RTX 30" >nul
if !errorlevel! equ 0 (
    set "REQ_FILE=requirements\requirements-rtx30.txt"
    set "GPU_SERIES=RTX 30 系列 (Ampere)"
    goto :selected
)

:: ─── 3b. 尝试按 compute capability 兜底判断 ──────────
echo  [WARN] 无法通过型号名判断 GPU 系列，尝试兜底检测...

for /f "tokens=*" %%i in ('nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2^>nul') do (
    set "CC=%%i"
    goto :cc_found
)
:cc_found

if "!CC!"=="" (
    echo  [ERROR] 无法检测 GPU 计算能力，请手动选择依赖文件
    goto :manual_select
)

:: CC 12.0 → Blackwell → RTX 50
echo !CC! | findstr "12\." >nul
if !errorlevel! equ 0 (
    set "REQ_FILE=requirements\requirements-rtx50.txt"
    set "GPU_SERIES=RTX 50 系列 (Blackwell, CC !CC!)"
    goto :selected
)

:: CC 8.9 → Ada Lovelace → RTX 40
echo !CC! | findstr "8\.9" >nul
if !errorlevel! equ 0 (
    set "REQ_FILE=requirements\requirements-rtx40.txt"
    set "GPU_SERIES=RTX 40 系列 (Ada Lovelace, CC !CC!)"
    goto :selected
)

:: CC 8.6 → Ampere → RTX 30
echo !CC! | findstr "8\.6" >nul
if !errorlevel! equ 0 (
    set "REQ_FILE=requirements\requirements-rtx30.txt"
    set "GPU_SERIES=RTX 30 系列 (Ampere, CC !CC!)"
    goto :selected
)

:: 兜底失败
echo  [ERROR] 未知 GPU 计算能力: !CC!，无法自动选择依赖
goto :manual_select

:selected
echo  [INFO] GPU 系列: !GPU_SERIES!
echo  [INFO] 依赖文件: !REQ_FILE!
goto :install

:manual_select
echo.
echo  请手动选择你的显卡系列：
echo     [1] RTX 30 系列 (3060/3070/3080/3090)
echo     [2] RTX 40 系列 (4060/4070/4080/4090)
echo     [3] RTX 50 系列 (5060/5070/5080/5090)
echo.
set /p CHOICE="  输入数字 (1/2/3): "
if "!CHOICE!"=="1" (
    set "REQ_FILE=requirements\requirements-rtx30.txt"
    set "GPU_SERIES=RTX 30 系列"
) else if "!CHOICE!"=="2" (
    set "REQ_FILE=requirements\requirements-rtx40.txt"
    set "GPU_SERIES=RTX 40 系列"
) else if "!CHOICE!"=="3" (
    set "REQ_FILE=requirements\requirements-rtx50.txt"
    set "GPU_SERIES=RTX 50 系列"
) else (
    echo  [ERROR] 无效选择
    pause
    exit /b 1
)

:: ─── 4. 安装依赖 ───────────────────────────────────
:install
if not exist "!REQ_FILE!" (
    echo  [ERROR] 找不到依赖文件: !REQ_FILE!
    pause
    exit /b 1
)

echo.
echo  ================================================
echo   即将安装 ScholarFlow 依赖
echo   目标: !GPU_SERIES!
echo   文件: !REQ_FILE!
echo  ================================================
echo.

if defined CONDA_ENV (
    echo  [STEP] 使用 conda 环境 "!CONDA_ENV!" 安装...
    call conda run -n !CONDA_ENV! pip install -r !REQ_FILE!
) else (
    echo  [STEP] 使用系统 Python 安装...
    pip install -r !REQ_FILE!
)

if !errorlevel! neq 0 (
    echo.
    echo  [ERROR] 依赖安装失败，请检查网络或 pip 配置
    pause
    exit /b 1
)

:: ─── 5. 验证安装 ───────────────────────────────────
echo.
echo  [VERIFY] 验证 PyTorch CUDA 是否可用...

if defined CONDA_ENV (
    call conda run -n !CONDA_ENV! python -c "import torch; print(f'PyTorch {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA version: {torch.version.cuda}'); print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"
) else (
    python -c "import torch; print(f'PyTorch {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA version: {torch.version.cuda}'); print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"
)

if !errorlevel! neq 0 (
    echo  [WARN] PyTorch CUDA 验证失败，可能是驱动版本不匹配
    echo         请检查 NVIDIA 驱动是否满足最低要求
)

echo.
echo  ================================================
echo   ScholarFlow 依赖安装完成！
echo  ================================================
echo.
pause
