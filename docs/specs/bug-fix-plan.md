# ScholarFlow Bug 修复方案

> 版本: v1.0 | 日期: 2026-07-21 | 基于三轮自审 Debug 报告

---

## 总览

| # | 严重度 | Bug | 状态 | 依赖 |
|---|--------|-----|------|------|
| 1 | 🔴 | LLM 后端碎片化：keyword_extractor 硬编码 Ollama | 待修复 | 需先完成配置管理 Phase 2 |
| 2 | 🔴 | review_service 硬编码 Ollama | 待修复 | 同上 |
| 3 | 🔴 | RAG 引擎硬编码 Ollama | 待修复 | 同上 |
| 4 | 🟠 | 翻译 max_tokens 未实际改为 4096 | 待修复 | 无 |
| 5 | 🟠 | 翻译竞态条件修复未落地 | 待修复 | 无 |
| 6 | 🟡 | HF_HUB_OFFLINE 被 .env 覆盖 | 待修复 | 需配合改 .env |
| 7 | 🟡 | database.py 默认值用 localhost 非 127.0.0.1 | 待修复 | 无 |
| 8 | 🟡 | Agent Tools 中 asyncio.run() 架构债务 | 待规划 | 需 LangChain async tool 调研 |
| 9 | 🟢 | SearchPage.tsx 类型安全 | 待修复 | 无 |
| 10 | 🔴 | review_service 忽略 LLM_BACKEND（与 BUG-2 同源） | 待修复 | 同 BUG-2 |
| 11 | 🟢 | start.bat 硬编码用户路径 | 待修复 | 无 |

---

## BUG-1 🔴 keyword_extractor 硬编码 Ollama

### 文件
`app/agent/keyword_extractor.py`

### 根因
`extract_keywords()` 函数内直接实例化 `OllamaGenerator`，调用 `_call_ollama_chat()` 向 Ollama `/api/chat` 发请求。完全不读取 `LLM_BACKEND` 环境变量。

### 影响
当 `LLM_BACKEND=deepseek` 时，关键词提取失败 → fallback 到正则分词 → "母乳低聚糖液质联用结构鉴定" 被拆成 `["human", "milk", "oligosaccharides", "LC", "MS"]`，丢失语义组合。

### 调用点（3 处触发）
```
1. main.py /search        (L1003) → extract_keywords(natural_query)
2. main.py /search/stream (L1059) → extract_keywords(natural_query)
3. agent/tools.py         (L56)   → extract_keywords(query)
```

### 解决方案

**Step 1**：在 `app/llm_factory.py` 中实现 `create_raw_llm()`（见配置管理 Spec Phase 1）。

**Step 2**：改造 `extract_keywords()`：

```python
# keyword_extractor.py — 改造后
from app.llm_factory import create_raw_llm

def extract_keywords(
    natural_query: str,
    temperature: float = 0.2,
    timeout: int = 120,
) -> ExtractionResult:
    if not natural_query or not natural_query.strip():
        return ExtractionResult(keywords=[], domain="", raw_query=natural_query, used_fallback=True)

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        few_shot=_FEW_SHOT_EXAMPLES,
        user_input=natural_query.strip(),
    )

    try:
        client = create_raw_llm()
        answer = client.chat(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=512,
        )
    except Exception as exc:
        return _fallback(natural_query, f"LLM 调用失败：{exc}")

    if not answer:
        return _fallback(natural_query, "LLM 返回为空")

    parsed = _parse_json_response(answer)
    # ... 后续解析逻辑不变
```

**关键变化**：
- 删除 `OllamaGenerator` import
- 删除 `ollama_model` / `ollama_base_url` 参数（由 `AppConfig` 统一管理）
- 用 `create_raw_llm().chat()` 替换 `generator._call_ollama_chat()`

**验证**：
```bash
# deepseek 模式
python -c "from app.agent.keyword_extractor import extract_keywords; \
  r = extract_keywords('我想找母乳低聚糖用液质联用做结构鉴定的文章'); \
  print(r.keywords, r.domain, r.used_fallback)"
# 期望: ['human milk oligosaccharides', 'LC-MS/MS', 'structure elucidation', ...]
```

---

## BUG-2 🔴 review_service 硬编码 Ollama

### 文件
`app/services/review_service.py`

### 根因
`generate_review()` 函数 L141-152 直接实例化 `OllamaGenerator`，调用 `_call_ollama_chat()`。

### 影响
`LLM_BACKEND=deepseek` 时综述功能完全不可用 → Agent `write_review` 工具返回错误。

### 解决方案

**改造 `generate_review()`**：

```python
# review_service.py — 改造后
from app.llm_factory import create_raw_llm

async def generate_review(
    topic: str,
    top_k: int = 10,
    min_score: Optional[float] = None,
    max_chars_per_evidence: int = 1000,
    # ▼ 以下参数改为可选，默认从 AppConfig 读取
    temperature: float | None = None,
    num_predict: int | None = None,
    timeout: int = 900,
) -> ReviewResult:
    # 1. 检索相关 chunks
    retriever = LocalChunkRetriever()
    evidences = await retriever.retrieve(...)

    if not evidences:
        return ReviewResult(topic=topic, review="当前本地文献库中没有检索到...", ...)

    # 2. 格式化为 context
    context = format_evidence_for_context(evidences, max_chars_per_evidence)

    # 3. 使用统一 LLM 客户端生成综述
    client = create_raw_llm()
    user_prompt = build_review_prompt(topic=topic, context=context)

    review_text = client.chat(
        system_prompt="你是科研文献综述写作助手。不要输出思考过程。只能基于给定 Context 中的证据撰写综述。",
        user_prompt=user_prompt,
        temperature=temperature or 0.3,
        max_tokens=num_predict or 2048,
    )
    # ...
```

**同步改动**：
- `main.py:/review` 端点 → 移除 `ollama_model` / `ollama_base_url` 参数（改为从 config 读取）
- `ReviewRequest` Pydantic 模型 → 移除 `ollama_model` / `ollama_base_url` 字段

---

## BUG-3 🔴 RAG 引擎硬编码 Ollama

### 文件
`app/rag/rag_engine.py` + `app/rag/generator.py`

### 根因
`LocalRagEngine.__init__` 默认 `ollama_model="qwen3:8b"`，内部创建 `OllamaGenerator`。

### 影响
`LLM_BACKEND=deepseek` 时 RAG 问答不可用 → Agent `ask_paper` 工具返回错误 → `/ask` 端点返回 500。

### 解决方案

**改造 `LocalRagEngine`**：

```python
# rag_engine.py — 改造后
from app.llm_factory import create_raw_llm

class LocalRagEngine:
    def __init__(
        self,
        embedding_model_name: str = DEFAULT_EMBEDDING_MODEL,
        embedding_device: str | None = None,
        # ▼ 生成参数（可选，默认从 config 读取）
        temperature: float | None = None,
        num_ctx: int | None = None,
        num_predict: int | None = None,
        timeout: int = 900,
        keep_alive: str = "30m",
    ) -> None:
        self.embedding_model_name = embedding_model_name
        self.embedding_device = embedding_device
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.timeout = timeout
        # 不再持有 OllamaGenerator，改为每次 ask 时通过工厂创建

    async def ask(self, question: str, ...) -> RagAnswer:
        # ... retriever 逻辑不变 ...

        # 生成回答
        client = create_raw_llm()
        answer = client.chat(
            system_prompt=build_system_prompt(language),
            user_prompt=build_rag_user_prompt(question, context, language),
            temperature=self.temperature or 0.2,
            max_tokens=self.num_predict or 512,
        )
        # ...
```

**废弃标记**：
- `generator.py` 中的 `OllamaGenerator` 类标记 `@deprecated`
- `generator.py` 中的 `GenerationResult` dataclass 保留（仍有使用方需要迁移）

---

## BUG-4 🟠 翻译 max_tokens 未实际改为 4096

### 文件
`app/main.py` — `/translate` 端点

### 当前代码（两处）

```python
# DeepSeek 路径 (L560)
"max_tokens": 2048,   # ← 应为 4096

# Ollama 路径 (L589)
"num_predict": 2048,  # ← 应为 4096
```

### 解决方案（两方案择一）

**方案 A（最小改动）**：直接改值
```diff
- "max_tokens": 2048,
+ "max_tokens": 4096,

- "options": {"temperature": 0.3, "num_predict": 2048},
+ "options": {"temperature": 0.3, "num_predict": 4096},
```

**方案 B（推荐，与配置管理统一）**：等 Phase 2 改造 `/translate` 端点使用 `create_raw_llm().chat()` 时，从 `AppConfig.translate_max_tokens` 读取。

```python
# 改造后
from app.llm_factory import create_raw_llm

@app.post("/translate")
async def translate(request: TranslateRequest) -> dict[str, Any]:
    text = request.text.strip()
    if not text:
        raise HTTPException(400, "text 不能为空")

    has_cjk = any('\u4e00' <= ch <= '\u9fff' for ch in text)
    if has_cjk:
        return {"translated": text, "original": text, "note": "已为中文，无需翻译"}

    prompt = f"你是一个专业的学术翻译助手。请将以下英文学术摘要翻译成中文...\n\n{text}"

    try:
        client = create_raw_llm()
        translated = client.chat(
            system_prompt="你是一个专业的学术翻译助手。",
            user_prompt=prompt,
            temperature=0.3,
            max_tokens=get_config().translate_max_tokens,  # 4096
        )
        return {"translated": translated, "original": text}
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))
```

**推荐方案 B**，理由：一次性消除 `/translate` 端点中 40+ 行的 if/else 分支（deepseek 路径 vs ollama 路径），代码量减半。

---

## BUG-5 🟠 翻译竞态条件修复未落地

### 文件
`frontend/src/pages/SearchPage.tsx`

### 当前代码（L112-127）

```tsx
const handleCardClick = (hit: SearchHit) => {
  setDetailHit(hit);
  setTranslatedAbstract(null);

  if (hit.abstract) {
    const hasCjk = /[\u4e00-\u9fff]/.test(hit.abstract);
    if (!hasCjk) {
      setTranslating(true);
      api.translate(hit.abstract)
        .then((res) => setTranslatedAbstract(res.translated))
        .catch(() => setTranslatedAbstract(null))       // ← 问题1: 无法区分失败/无需翻译
        .finally(() => setTranslating(false));
    }
  }
};
```

### 问题拆解

| 子问题 | 描述 |
|--------|------|
| **竞态条件** | 快速点击 A→B→C，A 的慢响应可能覆盖 C 的翻译结果 |
| **错误处理** | catch 设 `null`，UI 无法区分"翻译失败"和"无需翻译" |
| **状态残留** | 关闭模态框时 `translationError` 未重置 |

### 解决方案

```tsx
// SearchPage.tsx — 新增 imports
import { useState, useRef, useCallback } from 'react';

export function SearchPage({ onSelectPaper }: SearchPageProps) {
  // ... 现有 state ...

  // 新增：翻译请求 ID（竞态控制）
  const translateRequestIdRef = useRef(0);
  // 新增：翻译错误状态
  const [translationError, setTranslationError] = useState(false);

  const handleCardClick = useCallback((hit: SearchHit) => {
    setDetailHit(hit);
    setTranslatedAbstract(null);
    setTranslationError(false);  // ← 重置错误状态

    if (hit.abstract) {
      const hasCjk = /[\u4e00-\u9fff]/.test(hit.abstract);
      if (!hasCjk) {
        setTranslating(true);

        // 递增请求 ID
        translateRequestIdRef.current += 1;
        const requestId = translateRequestIdRef.current;

        api.translate(hit.abstract)
          .then((res) => {
            // 仅当请求 ID 仍匹配当前卡片时才更新
            if (requestId === translateRequestIdRef.current) {
              setTranslatedAbstract(res.translated);
              setTranslationError(false);
            }
          })
          .catch(() => {
            if (requestId === translateRequestIdRef.current) {
              setTranslatedAbstract(null);
              setTranslationError(true);  // ← 标记翻译失败
            }
          })
          .finally(() => {
            if (requestId === translateRequestIdRef.current) {
              setTranslating(false);
            }
          });
      }
    }
  }, []);

  // 关闭模态框时重置
  const handleCloseModal = () => {
    setDetailHit(null);
    setTranslatedAbstract(null);
    setTranslationError(false);
    setTranslating(false);
  };

  // ... JSX 中 ...
  {translationError && (
    <span className="text-red-500 text-sm">翻译失败，请稍后重试</span>
  )}
```

**改动要点**：
1. `useRef(0)` 计数器 → 每次点击递增 → 回调中校验 `requestId === current`
2. `translationError` 状态 → 区分"翻译失败"和"已为中文无需翻译"
3. `handleCloseModal` → 关闭模态框时全量重置

---

## BUG-6 🟡 HF_HUB_OFFLINE 被 .env 覆盖

### 文件
`start.bat` L55-57 + `.env` L32

### 当前执行顺序

```
start.bat: set HF_HUB_OFFLINE=1        ← 意图: 离线模式
start.bat: 加载 .env → set HF_HUB_OFFLINE=0  ← .env 覆盖了!
结果: HF_HUB_OFFLINE=0                   ← 离线模式静默失效
```

### 解决方案

**Step 1**：改 `.env`
```diff
- HF_HUB_OFFLINE=0
+ HF_HUB_OFFLINE=1
```

**Step 2**：改 `start.bat`
```diff
  if exist .env (
      for /f "usebackq tokens=1* delims==" %%a in (`findstr /v "^#" .env ^| findstr "."`) do (
-         set "%%a=%%b"
+         if not defined %%a set "%%a=%%b"
      )
  )
```

`if not defined` 的含义：仅当 `start.bat` 尚未设置该变量时，才从 `.env` 读取。这保护了 `start.bat` 中显式设置的变量不被 `.env` 覆盖。

**Step 3**：移除 `start.bat` 中不再需要的 `set HF_HUB_OFFLINE=1`（改由 `.env` 统一管理）。

---

## BUG-7 🟡 database.py 默认值 localhost → 127.0.0.1

### 文件
`app/storage/database.py` L51

### 当前代码
```python
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:scholarflow@localhost:5433/scholarflow",
)
```

### 解决方案
```diff
- "postgresql+asyncpg://postgres:scholarflow@localhost:5433/scholarflow",
+ "postgresql+asyncpg://postgres:scholarflow@127.0.0.1:5433/scholarflow",
```

**理由**：WSL2 下 `localhost` 先解析到 IPv6 `::1`，超时 5s 后回退 IPv4。`127.0.0.1` 强制 IPv4，避免此延迟。

**风险**：极低。`127.0.0.1` 是标准 IPv4 loopback，所有操作系统均支持。仅当用户通过 Unix socket 连接时需要 `localhost`，但 asyncpg 使用 TCP。

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

---

## BUG-10 🔴 review_service 忽略 LLM_BACKEND

**与 BUG-2 同源，见 BUG-2 方案。**

---

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

---

## 修复依赖关系

```
                    ┌──────────────────┐
                    │ Phase 1: config   │
                    │ + llm_factory     │
                    └────────┬─────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                   ▼
   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
   │ BUG-4 翻译   │   │ BUG-1 关键词 │   │ BUG-2/3/10  │
   │ max_tokens  │   │ 提取        │   │ RAG+综述     │
   └─────────────┘   └─────────────┘   └─────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                   ▼
   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
   │ BUG-5 竞态   │   │ BUG-6/7/11 │   │ BUG-8/9     │
   │ (前端独立)   │   │ 配置/启动   │   │ 债务/类型   │
   └─────────────┘   └─────────────┘   └─────────────┘
```

- **BUG-4** 可独立修复（直接改值），但推荐等工厂就绪后一起改
- **BUG-5** 纯前端，可随时独立修复
- **BUG-6/7/11** 互不依赖，可并行修复
- **BUG-1/2/3/10** 依赖配置管理 Phase 1-3 完成

---

## 建议修复批次

### Batch 1（立即可做，无依赖）
- BUG-5：翻译竞态 + 错误处理（纯前端）
- BUG-7：database.py 改 `127.0.0.1`
- BUG-9：SearchPage 类型安全
- BUG-11：start.bat 自动检测 Python

### Batch 2（需配置管理 Phase 1-2 完成）
- BUG-4：翻译 max_tokens → 4096
- BUG-1：keyword_extractor 改工厂

### Batch 3（需配置管理 Phase 1-3 完成）
- BUG-2/10：review_service 改工厂
- BUG-3：RAG 引擎改工厂

### Batch 4（清理收尾）
- BUG-6：HF_HUB_OFFLINE 一致性
- BUG-8：Agent Tools async 化（长期）
