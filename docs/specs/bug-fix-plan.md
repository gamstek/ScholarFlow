# ScholarFlow 待修复 Bug 清单

> 版本: v1.0 | 日期: 2026-07-21 | 更新: 2026-07-27
>
> 已修复（不再列出）：BUG-1~7, BUG-10（LLM 硬编码、翻译 max_tokens、HF_HUB_OFFLINE、database.py 等）

---

## BUG-8 🟡 Agent Tools 中 asyncio.run() 架构债务

### 文件
`app/agent/tools.py` — 6 处：L64, L137, L197, L229, L261, L342

### 当前状态
能工作（`run_agent()` 同步 → FastAPI 放线程池），但不优雅。

### 根因
LangChain `@tool` 装饰器默认创建同步 Tool。Tool 内部调用 async 数据库操作 → 被迫用 `asyncio.run()` 桥接。

### 解决方案（分两步）

**Step 1（短期）**：不做结构性改动。仅确保 `run_agent()` 始终在同步上下文中调用。

**Step 2（长期）**：迁移到 LangChain async tool

```python
# tools.py — 长期改造
@tool
async def list_library() -> str:          # ← async def
    from app.storage.repositories import PaperRepository
    repo = PaperRepository()
    papers = await repo.list_papers(limit=50, offset=0)  # ← 直接 await
    # ... 不需要 asyncio.run()!
```

**附带收益**：可以去掉 `database.py` 中的 `NullPool`，恢复连接池 → 高并发性能提升。

**风险**：改动面大（6 个 Tool + `database.py` poolclass），需要充分测试。

---

## BUG-9 🟢 SearchPage.tsx 类型安全

### 文件
`frontend/src/pages/SearchPage.tsx`

### 问题
`importingIds` 和 `importedIds` 类型为 `Set<number>`，但实际存储的是字符串 key（DOI 或标题）。

### 解决方案

```diff
- const [importingIds, setImportingIds] = useState<Set<number>>(new Set());
+ const [importingIds, setImportingIds] = useState<Set<string>>(new Set());
```

**改动范围**：`SearchPage.tsx` 中所有 `Set<number>` → `Set<string>`，约 4 处。

---

## BUG-11 🟢 start.bat 硬编码用户路径

### 文件
`start.bat`

### 问题
Python 路径检测已有自适应逻辑（venv → conda → 系统），但缺少对边界情况的完整覆盖。

### 解决方案
确保 `start.bat` 的 Python 检测覆盖所有常见场景，当前版本基本满足，后续可按需增强。

---

## BUG-8 🟡 Agent Tools 中 asyncio.run() 架构债务

### 文件
`app/agent/tools.py` — 6 处：L64, L137, L197, L229, L261, L342

### 当前状态
能工作（`run_agent()` 同步 → FastAPI 放线程池），但不优雅。

### 根因
LangChain `@tool` 装饰器默认创建同步 Tool。Tool 内部调用 async 数据库操作 → 被迫用 `asyncio.run()` 桥接。

### 解决方案（分两步）

**Step 1（短期）**：不做结构性改动。仅确保 `run_agent()` 始终在同步上下文中调用。

**Step 2（长期）**：迁移到 LangChain async tool

LangChain 支持 async tool —— 工具函数可以是 `async def`：

```python
# tools.py — 长期改造
@tool
async def list_library() -> str:          # ← async def
    from app.storage.repositories import PaperRepository
    repo = PaperRepository()
    papers = await repo.list_papers(limit=50, offset=0)  # ← 直接 await
    # ... 不需要 asyncio.run()!
```

然后 `get_agent()` 中创建的 agent 会自动识别 async tools 并在 event loop 中调用它们。

**附带收益**：可以去掉 `database.py` 中的 `NullPool`，恢复连接池 → 高并发性能提升。

**风险**：改动面大（6 个 Tool + `database.py` poolclass），需要充分测试。

---

## BUG-9 🟢 SearchPage.tsx 类型安全

### 文件
`frontend/src/pages/SearchPage.tsx` L180-185

### 当前代码
```tsx
const key = hit.title;
setImportingIds((prev) => new Set(prev).add(key as unknown as number));
```

### 解决方案
```diff
- const key = hit.title;
- setImportingIds((prev) => new Set(prev).add(key as unknown as number));
+ // 用 DOI 或标题作为唯一 key
+ const key = hit.doi || hit.title;
+ setImportingIds((prev) => new Set(prev).add(key));
```

并修改 `importingIds` 类型：
```diff
- const [importingIds, setImportingIds] = useState<Set<number>>(new Set());
+ const [importingIds, setImportingIds] = useState<Set<string>>(new Set());
```

同理修改 `importedIds`。

**改动范围**：`SearchPage.tsx` 中所有 `Set<number>` → `Set<string>`，约 4 处。



## BUG-11 🟢 start.bat 硬编码用户路径

### 文件
`start.bat` L60

### 当前代码
```batch
set PYTHON=C:\Users\HP\.conda\envs\scholarflow\python.exe
```

### 解决方案

```batch
:: 自动检测 scholarflow conda 环境的 python 路径
set PYTHON=
for /f "tokens=*" %%i in ('where conda 2^>nul') do set CONDA_CMD=%%i
if defined CONDA_CMD (
    for /f "tokens=*" %%i in ('conda info --envs ^| findstr scholarflow') do (
        for /f "tokens=2 delims= " %%j in ("%%i") do (
            if exist "%%j\python.exe" set "PYTHON=%%j\python.exe"
        )
    )
)
if not defined PYTHON (
    echo [ERROR] 找不到 scholarflow conda 环境。请手动设置 PYTHON 变量。
    pause
    exit /b 1
)
echo [OK] Python: %PYTHON%
```

**或者更简单**（如果用户已激活 conda 环境）：
```batch
:: 如果 conda 环境已激活，直接用当前 python
where python >nul 2>nul
if %errorlevel% equ 0 (
    set PYTHON=python
) else (
    echo [ERROR] 找不到 python。请先激活 scholarflow 环境。
    pause
    exit /b 1
)
```


