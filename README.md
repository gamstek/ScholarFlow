# ScholarFlow

> 个人文献工作站 — 智能采集、语义检索、RAG 问答、文献综述，一站式本地运行。

---

## 功能概览

| 功能 | 说明 |
|---|---|
| **文献检索** | 自然语言或关键词搜索，LLM 自动提取关键词+领域，6 数据源并行检索，实时进度显示，支持按相关度/时间排序 |
| **元数据查看** | 点击检索卡片弹出详情模态框，展示完整元数据，英文摘要自动翻译为中文 |
| **一键入库** | 库外论文点击入库，后台自动完成 PDF 下载→解析→切块→索引 |
| **论文查看器** | 在线阅读全文（文本/PDF 双模式），显示本地存储路径 |
| **文献库管理** | 查看所有入库文献及处理状态，支持查看源数据、上传 PDF、删除文献 |
| **RAG 问答** | 对本地文献库提问，基于检索证据回答，附带引用来源 |
| **文献综述** | 输入主题，自动检索相关文献并生成结构化 Markdown 综述 |
| **Agent 对话** | 自然语言对话，Agent 自动决策调用 5 个工具，支持多轮上下文记忆 |

---

## 1. 环境要求

### 硬件

| 项目 | 最低要求 | 推荐 |
|---|---|---|
| GPU | 无（可 CPU 运行） | NVIDIA RTX 3060+（6GB+ 显存） |
| 内存 | 8 GB | 16 GB+ |
| 磁盘 | 10 GB | 20 GB+（含 PDF 存储） |

### 软件

| 依赖 | 版本 | 说明 |
|---|---|---|
| **Python** | 3.10 ~ 3.12 | 推荐使用 conda 环境 `scholarflow` |
| **PostgreSQL** | 16+ | 通过 Docker 运行，端口 5433 |
| **Docker Desktop** | 最新版 | 运行 PostgreSQL 容器 |
| **Node.js** | 18+ | 仅修改前端代码时需要 |

### LLM 后端（二选一）

| 方式 | 配置 | 适用场景 |
|---|---|---|
| **Ollama 本地** | 安装 Ollama + `ollama pull qwen3:8b` | 离线使用，无需 API Key |
| **云端 API** | `.env` 中设置 `LLM_BACKEND=deepseek` + `CLOUD_API_KEY` | 更快响应，无本地显存要求 |

### Embedding 模型

项目使用 **BGE-M3**（`BAAI/bge-m3`），约 2.2 GB，向量维度 1024。

模型统一存放在项目 `embedding/` 目录下，首次需手动下载：

```powershell
# 推荐：Python 脚本下载（支持国内镜像加速）
python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-m3', local_dir='embedding/bge-m3', ignore_patterns=['*.onnx*', 'onnx/**', 'imgs/**', '*.jpg', '*.webp', '*.pt', '*.md', '.gitattributes'])"

# 国内镜像加速（在命令末尾加 endpoint 参数）
python -c "...snapshot_download(..., endpoint='https://hf-mirror.com')"
```

> 详见 `embedding/README.md`

---

## 2. 环境检测

安装依赖前，先运行检测脚本确认本机是否满足要求：

```powershell
python .github\skills\check-dependencies\check_env.py
```

检测项包括：

| 检测项 | 说明 |
|---|---|
| Python 版本 | 3.10 ~ 3.12 |
| pip 关键包 | torch, sentence-transformers, faiss-cpu, fastapi 等 |
| PyTorch CUDA | GPU 型号与 CUDA 版本兼容性 |
| Ollama 服务 | 本地 LLM 后端是否运行 |
| PostgreSQL | Docker 容器状态 |
| FAISS 索引 | `data/index/` 是否存在 |
| BGE-M3 模型 | `embedding/bge-m3/` 或 HuggingFace 缓存 |

输出结果会标注 ✅/❌ 并给出修复建议。

---

## 3. 依赖准备

### 3.1 创建 Python 环境

```powershell
conda create -n scholarflow python=3.11 -y
conda activate scholarflow
```

### 3.2 安装依赖

项目已按 GPU 架构分拆依赖文件（RTX 30/40/50 系列），运行智能安装脚本自动检测：

```powershell
install_deps.bat
```

脚本会自动：检测 GPU 型号 → 匹配 compute capability → 选择对应 `requirements-rtx*.txt` → pip 安装 → 验证 `torch.cuda.is_available()`。

> 手动指定架构：`pip install -r requirements/requirements-rtx50.txt`（替换为你对应的文件）

### 3.3 下载 Embedding 模型

```powershell
# 下载 BGE-M3 到项目 embedding/ 目录（约 2.2 GB）
python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-m3', local_dir='embedding/bge-m3', ignore_patterns=['*.onnx*', 'onnx/**', 'imgs/**', '*.jpg', '*.webp', '*.pt', '*.md', '.gitattributes'])"
```

> 国内用户追加 `, endpoint='https://hf-mirror.com'` 到 `snapshot_download()` 参数中

### 3.4 创建数据库容器

```powershell
# 国内用户先走镜像源拉取
docker pull docker.m.daocloud.io/library/postgres:16
docker tag docker.m.daocloud.io/library/postgres:16 postgres:16

# 创建并启动容器（端口 5433，避免与本机 PostgreSQL 冲突）
docker run -d --name scholarflow-pg -p 5433:5432 -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=scholarflow -e POSTGRES_DB=scholarflow postgres:16
```

验证：

```powershell
docker ps --filter "name=scholarflow-pg"
```

### 3.5 （可选）拉取 Ollama 模型

```powershell
ollama pull qwen3:8b
```

---

## 4. .env 配置

项目根目录已有 `.env` 模板，用文本编辑器打开修改：

```env
# ===== 数据库（一般无需修改）=====
DATABASE_URL=postgresql+asyncpg://postgres:scholarflow@127.0.0.1:5433/scholarflow

# ===== LLM 后端选择 =====
# ollama（本地）| deepseek | openai | qwen（云端）
LLM_BACKEND=deepseek

# 云端 API（LLM_BACKEND 为云端时生效）
CLOUD_API_KEY=sk-your-key-here        # 替换为你的 API Key
CLOUD_API_BASE=https://api.deepseek.com/v1
CLOUD_MODEL=deepseek-chat

# 本地 Ollama（LLM_BACKEND=ollama 时生效）
OLLAMA_MODEL=qwen3:8b
OLLAMA_BASE_URL=http://localhost:11434

# ===== BGE-M3 嵌入模型 =====
BGE_MODEL_PATH=embedding/bge-m3       # 指向本地模型目录
HF_HUB_OFFLINE=1                      # 1=离线加载，不联网验证
```

**快速切换 LLM**：只需改 `LLM_BACKEND` 一行（`ollama` ↔ `deepseek` ↔ `openai` ↔ `qwen`），重启即生效。

---

## 5. 启动

**双击 `start.bat`**，脚本自动完成：

1. 检测/启动 PostgreSQL Docker 容器
2. 检测/启动 Ollama 服务
3. 加载 `.env` 配置
4. 启动 FastAPI 后端 + 预热 BGE-M3 模型
5. 自动打开浏览器 `http://localhost:8000`

停止：`Ctrl+C`。

> 前端已预构建在 `frontend/dist/`。修改前端代码后执行 `cd frontend && npm run build` 重新构建。

---

## API 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/health` | 健康检查（含 LLM/Embedding 状态） |
| `GET` | `/stats` | 数据库统计 |
| `POST` | `/search` | 跨源文献检索 |
| `POST` | `/search/stream` | 流式检索（SSE 实时进度） |
| `POST` | `/translate` | 英文摘要翻译为中文 |
| `POST` | `/ask` | RAG 问答 |
| `POST` | `/review` | 文献综述生成 |
| `POST` | `/agent/chat` | Agent 对话 |
| `GET` | `/agent/sessions` | 会话列表 |
| `GET` | `/agent/sessions/{id}` | 会话详情 |
| `DELETE` | `/agent/sessions/{id}` | 删除会话 |
| `GET` | `/papers` | 文献库列表 |
| `GET` | `/papers/{id}` | 文献详情 |
| `GET` | `/papers/{id}/text` | 文献全文 |
| `GET` | `/papers/{id}/pdf` | 下载 PDF |
| `GET` | `/papers/{id}/chunks` | 文本块列表 |
| `POST` | `/papers/import` | 文献入库 |
| `POST` | `/papers/{id}/process` | 触发后台流水线 |
| `POST` | `/papers/{id}/upload-pdf` | 上传 PDF |
| `POST` | `/papers/upload-pdf` | 独立上传 PDF 入库 |
| `DELETE` | `/papers/{id}` | 删除文献（含本地文件） |
| `POST` | `/chunks/search` | 检索文本块 |
| `POST` | `/rag/warmup` | 预热 embedding + FAISS |

---

## 数据源

| 数据源 | 后端 | 说明 |
|---|---|---|
| Europe PMC | Europe PMC REST API | 通用生物医学（Nature/Science/Cell 底层也走此 API） |
| Semantic Scholar | S2 Graph API | 通用学术搜索，2 亿+ 论文 |
| arXiv | arXiv API | 预印本 |
| Nature | Europe PMC + 期刊过滤 | Nature 系列期刊 |
| Science | Europe PMC + 期刊过滤 | Science 系列期刊 |
| Cell | Europe PMC + 期刊过滤 | Cell Press 期刊 |

---

## Agent 工具

| 工具 | 说明 |
|---|---|
| `search_papers` | 跨源检索论文（支持自然语言） |
| `list_library` | 查看本地已入库文献列表 |
| `view_paper` | 查看库中论文全文 |
| `ask_paper` | RAG 问答（基于本地文献库） |
| `write_review` | 撰写文献综述 |

---

## 数据目录

```
data/
├── sessions.json    # Agent 对话会话持久化
├── index/           # FAISS 向量索引 + chunk 元数据
├── papers/          # 下载的 PDF 原文
└── texts/           # PDF 解析后的结构化 JSON
```

---

## 技术架构

```
用户 → React 前端 → FastAPI 后端
                      ├── LangChain Agent
                      │   ├── search_papers / list_library
                      │   ├── view_paper / ask_paper / write_review
                      │   └── LLM: Ollama / DeepSeek 可切换
                      ├── 文献采集层（6 数据源，并行检索）
                      ├── 文档处理层（PDF 解析 → 切块）
                      ├── RAG 引擎（BGE-M3 + FAISS）
                      └── PostgreSQL 存储
```

| 层级 | 技术 |
|---|---|
| 后端 | FastAPI + SQLAlchemy async + asyncpg |
| 前端 | React 18 + TypeScript + Vite + Tailwind CSS |
| LLM | Ollama (qwen3:8b) / DeepSeek (deepseek-chat) |
| Embedding | BGE-M3 (sentence-transformers) |
| 向量检索 | FAISS |
| Agent | LangChain create_agent + langchain-ollama + langchain-openai |
| 数据库 | PostgreSQL 16 (Docker) |
| PDF 解析 | PyMuPDF |

---

## 项目结构

```
ScholarFlow/
├── app/
│   ├── agent/                    # LangChain Agent
│   │   ├── agent.py              # Agent 工厂 + 会话管理
│   │   ├── tools.py              # 5 个 Tool 定义
│   │   └── keyword_extractor.py  # LLM 关键词提取
│   ├── harvest/                  # 文献采集层
│   │   ├── harvester.py          # 采集总控（并行检索+去重+评分）
│   │   └── literature/           # 6 个数据源客户端
│   ├── document/                 # PDF 解析 + 章节识别 + 切块
│   ├── domain/                   # 语义评分（查询驱动）
│   ├── rag/                      # RAG 引擎（embedding+检索+生成）
│   ├── services/                 # 业务服务层
│   ├── storage/                  # 数据库 ORM + 文件存储 + 仓库
│   ├── api/                      # 流水线路由
│   └── main.py                   # FastAPI 入口（27 个端点）
├── frontend/                     # React 前端
│   └── src/
│       ├── pages/                # 6 个页面
│       ├── components/           # 通用组件
│       ├── hooks/                # React Query hooks
│       └── lib/                  # API 调用层 + 类型定义
├── scripts/                      # 命令行工具
├── requirements/                 # GPU 分架构依赖文件
├── data/                         # 运行时数据
├── start.bat                     # 一键启动
├── install_deps.bat              # GPU 智能依赖安装
└── .env                          # 环境配置
```

---

## 常见问题

**Q: 启动后白屏？** 按 `Ctrl+Shift+R` 强制刷新浏览器。

**Q: 修改前端代码后没变化？** 执行 `cd frontend && npm run build` 重新构建。

**Q: 如何切换 LLM？** 修改 `.env` 中 `LLM_BACKEND`（`ollama` 或 `deepseek`），重启服务。

**Q: 检索很慢？** 已优化为多源并行检索 + GPU embedding。3 个源约 4 秒。
