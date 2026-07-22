# ScholarFlow 配置管理方案 Spec

> 版本: v1.0 | 日期: 2026-07-21 | 状态: 待实施

---

## 1. 问题陈述

### 1.1 当前架构的四个痛点

```
┌──────────────────────────────────────────┐
│  痛点 1: 配置碎片化                       │
│  .env 有 7 个变量，但 LLM_BACKEND 只在    │
│  agent.py:get_agent() 一处被消费。        │
│  keyword_extractor / rag_engine /        │
│  review_service / translate 共 5 个模块   │
│  各自硬编码 LLM 选择。                    │
├──────────────────────────────────────────┤
│  痛点 2: start.bat 与 .env 互相覆盖       │
│  start.bat set HF_HUB_OFFLINE=1          │
│  → .env 加载后覆盖为 HF_HUB_OFFLINE=0    │
│  → 离线模式静默失效                       │
├──────────────────────────────────────────┤
│  痛点 3: 默认值散落各处，无集中管理         │
│  15+ 处硬编码 "qwen3:8b" /               │
│  "http://localhost:11434" / 5433 等       │
│  改一个默认值需要搜索+批量替换             │
├──────────────────────────────────────────┤
│  痛点 4: 无环境校验，错配静默失败          │
│  LLM_BACKEND=deepseek 但 Ollama 未运行   │
│  → keyword_extractor 静默降级到 fallback  │
│  → 用户不知道关键词提取质量已下降          │
└──────────────────────────────────────────┘
```

### 1.2 受影响模块清单

| 模块 | 文件 | 硬编码内容 | LLM_BACKEND 感知 |
|------|------|-----------|-----------------|
| Agent 决策 | `agent/agent.py` | ChatOllama/ChatOpenAI | ✅ 已感知 |
| 关键词提取 | `agent/keyword_extractor.py` | OllamaGenerator | ❌ 硬编码 Ollama |
| RAG 问答 | `rag/rag_engine.py` | OllamaGenerator | ❌ 硬编码 Ollama |
| RAG 生成器 | `rag/generator.py` | urllib → Ollama /api/chat | ❌ 仅支持 Ollama |
| 综述生成 | `services/review_service.py` | OllamaGenerator | ❌ 硬编码 Ollama |
| 翻译端点 | `main.py:/translate` | httpx → Ollama 或 DeepSeek | ✅ 已感知 |
| 数据库 | `storage/database.py` | DATABASE_URL 默认值 | N/A |

---

## 2. 设计目标

1. **单一配置源**：所有模块从同一个 `AppConfig` 实例读取配置，不再各自读环境变量或硬编码
2. **LLM 透明切换**：改 `.env` 中 `LLM_BACKEND=deepseek` 后，所有 6 个 LLM 调用点全部自动切换
3. **启动时可校验**：FastAPI lifespan 中检测配置一致性，不匹配时打印明确警告
4. **向后兼容**：`.env` 现有变量名不变，`start.bat` 改动最小化
5. **零破坏性**：分阶段实施，每个阶段独立可回滚

---

## 3. 架构设计

### 3.1 总体结构

```
                    ┌──────────────┐
                    │   .env 文件   │
                    │  (7 变量不变)  │
                    └──────┬───────┘
                           │ Pydantic Settings
                           ▼
                  ┌─────────────────┐
                  │   AppConfig     │  ← 单例，模块级延迟加载
                  │  (app/config.py) │
                  └────────┬────────┘
                           │ get_config()
          ┌────────────────┼────────────────┐
          ▼                ▼                 ▼
   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
   │ LLMFactory  │  │ DBFactory   │  │ EMBFactory  │
   │ .create()   │  │ .engine()   │  │ .embedder() │
   │ .raw_client │  │             │  │             │
   └──────┬──────┘  └─────────────┘  └─────────────┘
          │
    ┌─────┴─────┐
    ▼           ▼
ChatOllama   ChatOpenAI       ← LangChain 兼容对象
OllamaRaw    OpenAIClient     ← 底层 HTTP 客户端
```

### 3.2 核心组件

#### 3.2.1 `AppConfig`（`app/config.py`）

所有配置的单一事实来源。使用 Pydantic Settings 自动从 `.env` 加载。

```python
from pydantic_settings import BaseSettings

class AppConfig(BaseSettings):
    """ScholarFlow 全局配置 —— 唯一配置入口。"""

    # ========== 数据库 ==========
    database_url: str = (
        "postgresql+asyncpg://postgres:scholarflow@127.0.0.1:5433/scholarflow"
    )

    # ========== LLM 后端选择 ==========
    llm_backend: str = "ollama"          # ollama | deepseek | openai | qwen

    # 本地 Ollama
    ollama_model: str = "qwen3:8b"
    ollama_base_url: str = "http://localhost:11434"

    # 云端 API（LLM_BACKEND != ollama 时生效）
    cloud_api_key: str = ""
    cloud_api_base: str = "https://api.deepseek.com/v1"
    cloud_model: str = "deepseek-chat"

    # ========== Embedding ==========
    bge_model_path: str = "embedding/bge-m3"
    hf_hub_offline: bool = False

    # ========== 生成默认参数 ==========
    default_temperature: float = 0.3
    default_num_ctx: int = 4096
    default_num_predict: int = 512
    translate_max_tokens: int = 4096
    review_num_predict: int = 2048

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # 忽略 .env 中未定义的字段，向前兼容

    @property
    def is_cloud_backend(self) -> bool:
        return self.llm_backend != "ollama"
```

#### 3.2.2 `LLMFactory`（`app/llm_factory.py`）

统一 LLM 创建入口，其他模块不再直接 import `ChatOllama` / `ChatOpenAI` / `OllamaGenerator`。

提供两层接口：
- **LangChain 层**：返回 `BaseChatModel`，供 Agent / LangChain 工具使用
- **Raw 层**：返回原始 HTTP 客户端，供 `keyword_extractor` / `review_service` / `translate` 使用

```python
from app.config import get_config

def create_chat_model(**overrides) -> BaseChatModel:
    """创建 LangChain 兼容的 ChatModel。Agent / RAG 引擎使用。"""
    ...

def create_raw_llm() -> "RawLLMClient":
    """创建底层 HTTP 客户端。关键词提取 / 综述 / 翻译使用。"""
    ...
```

**RawLLMClient 接口**（统一 Ollama `/api/chat` 和 OpenAI `/chat/completions`）：

```python
class RawLLMClient(ABC):
    @abstractmethod
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 512,
    ) -> str: ...

class OllamaRawClient(RawLLMClient): ...
class OpenAIRawClient(RawLLMClient): ...
```

#### 3.2.3 单例管理

```python
# app/config.py
_config: AppConfig | None = None
_lock = threading.Lock()

def get_config() -> AppConfig:
    global _config
    if _config is None:
        with _lock:
            if _config is None:
                _config = AppConfig()
    return _config
```

### 3.3 调用方改造映射

| 原调用方 | 原做法 | 新做法 |
|---------|--------|--------|
| `agent.py:get_agent()` | `ChatOllama(...)` 或 `ChatOpenAI(...)` | `create_chat_model()` |
| `keyword_extractor.py` | `OllamaGenerator(...)._call_ollama_chat()` | `create_raw_llm().chat()` |
| `rag_engine.py` | `OllamaGenerator(...)` | `create_raw_llm()` 注入到 `LocalRagEngine` |
| `review_service.py` | `OllamaGenerator(...)._call_ollama_chat()` | `create_raw_llm().chat()` |
| `main.py:/translate` | httpx 直接调 Ollama 或 DeepSeek | `create_raw_llm().chat()` |
| `main.py:/health` | 读 `LLM_BACKEND` + httpx 探测 | `get_config()` + `create_raw_llm().health_check()` |

### 3.4 startup 校验

在 `main.py` 的 `lifespan` 中增加配置一致性检查：

```python
async def lifespan(app: FastAPI):
    await init_db()
    _warmup_embedding()
    _validate_config()   # ← 新增

def _validate_config():
    cfg = get_config()
    warnings = []

    if cfg.llm_backend == "ollama":
        # 检查 Ollama 是否可达
        ...
    elif cfg.llm_backend in ("deepseek", "openai", "qwen"):
        if not cfg.cloud_api_key:
            warnings.append("CLOUD_API_KEY 未设置，云端 API 将不可用")
        ...

    if warnings:
        for w in warnings:
            print(f"[Config] ⚠ {w}")
    else:
        print(f"[Config] ✓ LLM backend: {cfg.llm_backend}, model: {cfg.active_model}")
```

---

## 4. 实施计划（5 个阶段）

### Phase 1：基础设施（零破坏）

- 新建 `app/config.py`（`AppConfig` + `get_config()`）
- 新建 `app/llm_factory.py`（`create_chat_model()` + `create_raw_llm()` + `RawLLMClient` 接口 + `OllamaRawClient` + `OpenAIRawClient`）
- **不修改任何现有模块**，仅确保新文件可 import 且不报错
- 验证：`python -c "from app.config import get_config; print(get_config().llm_backend)"`

### Phase 2：低风险模块迁移

- `agent.py:get_agent()` → 改用 `create_chat_model()`
- `main.py:/translate` → 改用 `create_raw_llm().chat()`
- `main.py:/health` → 改用 `get_config()`
- 验证：启动服务，分别测试 Agent 对话和翻译端点

### Phase 3：核心模块迁移

- `keyword_extractor.py` → 改用 `create_raw_llm().chat()`，删除 `OllamaGenerator` 依赖
- `rag_engine.py` → `LocalRagEngine.__init__` 接受 `RawLLMClient` 参数（默认从工厂创建）
- 验证：自然语言搜索 + RAG 问答均正常工作

### Phase 4：剩余模块 + 清理

- `review_service.py` → 改用 `create_raw_llm().chat()`
- `generator.py` → 标记为 deprecated，后续版本移除
- `start.bat` → `if not defined` 保护 `HF_HUB_OFFLINE`
- `.env` → `HF_HUB_OFFLINE=1`（修正）
- `database.py` 默认值 → `127.0.0.1`（修正 localhost 问题）
- 验证：全功能回归测试

### Phase 5：startup 校验

- `main.py:lifespan` → 增加 `_validate_config()`
- 前端健康检查展示配置摘要
- 验证：故意设错 `.env` 配置，确认启动时打印明确警告

---

## 5. `.env` 变量兼容性

现有 `.env` 变量**全部保留**，不做任何重命名：

| 变量名 | 状态 | 说明 |
|--------|------|------|
| `DATABASE_URL` | 保留 | 默认值从 localhost 改为 127.0.0.1 |
| `LLM_BACKEND` | 保留 | 新增全局生效范围 |
| `OLLAMA_MODEL` | 保留 | |
| `OLLAMA_BASE_URL` | 保留 | |
| `CLOUD_API_KEY` | 保留 | |
| `CLOUD_API_BASE` | 保留 | |
| `CLOUD_MODEL` | 保留 | |
| `BGE_MODEL_PATH` | 保留 | |
| `HF_HUB_OFFLINE` | 保留 | 修正值为 1 |

---

## 6. `start.bat` 改动

```diff
- set HF_HUB_OFFLINE=1
  :: Load .env if exists (for DATABASE_URL etc.)
  if exist .env (
      for /f "usebackq tokens=1* delims==" %%a in (`findstr /v "^#" .env ^| findstr "."`) do (
-         set "%%a=%%b"
+         if not defined %%a set "%%a=%%b"
      )
  )
```

改动说明：`if not defined` 确保 `start.bat` 中已设置的变量不被 `.env` 覆盖。同时 `.env` 中 `HF_HUB_OFFLINE` 需改为 `1`。

---

## 7. 风险与回滚

| 风险 | 影响 | 缓解 |
|------|------|------|
| 工厂创建的 ChatModel 行为与原代码不同 | Agent 回答质量变化 | Phase 2 先在 deepseek 模式验证，与原 Agent 对比 |
| `RawLLMClient` 接口不覆盖所有 Ollama 参数 | think/keep_alive 等高级参数丢失 | 接口预留 `**kwargs` 透传 |
| `OllamaGenerator` 有 8 个调用方 | 遗漏某处未迁移 | grep 全项目 `OllamaGenerator` 确保 0 残留引用 |

回滚方式：每个 Phase 独立提交一个 commit，出问题直接 `git revert` 该 commit。
