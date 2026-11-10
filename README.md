# ScholarFlow-Bio

> 生物医学文献智能体 — 智能采集、语义检索、RAG 问答、文献综述，一站式本地运行。
> 推荐使用 **PowerShell 5.1+** 终端执行命令。

---

## 功能概览

| 功能 | 说明 |
|---|---|
| **文献检索** | 自然语言或关键词搜索，LLM 自动提取关键词+领域，8 数据源并行检索，实时进度显示，支持按相关度/时间/引用量排序 |
| **作者检索** | 直接输入作者名查找其论文，支持中文名自动扩展为 8 种英文拼音变体（如"张爽"→Shuang Zhang / Zhang Shuang / …），无需填写关键词 |
| **元数据查看** | 点击检索卡片弹出详情模态框，展示完整元数据（标题、作者、DOI、期刊、年份），英文摘要自动翻译为中文 |
| **一键入库** | 库外论文点击入库，后台自动完成 PDF 下载→解析→切块→索引；Agent 对话中也可直接说"入库第3篇" |
| **论文查看器** | 在线阅读全文（文本/PDF 双模式），显示本地存储路径 |
| **文献库管理** | 查看所有入库文献及处理状态，支持查看源数据、上传 PDF、删除文献 |
| **RAG 问答** | 对本地文献库提问，基于检索证据回答，附带引用来源 |
| **文献综述** | 输入主题，自动检索相关文献并生成结构化 Markdown 综述 |
| **Agent 对话** | 自然语言对话，Agent 自动调用 7 个工具（检索/入库/问答/综述/网页搜索），支持多轮记忆、快速/深度搜索模式 |

---

## 1. 环境要求

### Docker 镜像运行（GitHub CI 构建）

GitHub Actions 工作流 `.github/workflows/docker-image.yml` 会在推送到 `master`、推送 `v*` 标签或手动触发时构建 **Linux amd64 CPU 镜像**，通过 PostgreSQL、首页静态资源和 API 启动检查后发布到 GHCR。PR 只构建和检查，不发布。

镜像地址：`ghcr.io/gamstek/scholarflow:latest`，同时保留分支、版本标签及 `sha-<短提交号>` 标签。使用仓库自带的 `GITHUB_TOKEN` 发布，无需额外配置仓库密钥。

镜像内包含 Python `scholarflow` 环境、后端依赖和前端构建产物。依赖下载使用清华 Conda、阿里云 PyPI、上海交大 PyTorch 和 npmmirror 镜像源；`.env`、文献数据和模型不进入镜像。

镜像首次发布后，在项目根目录执行：

```powershell
# 准备 .env：已有配置时直接使用，首次使用时从 .env.example 复制
# 云端模型需配置 LLM_BACKEND、CLOUD_API_KEY、CLOUD_API_BASE、CLOUD_MODEL
# 确保 embedding/bge-m3 中已备好模型（见下文模型下载说明）
docker compose pull
docker compose up -d
docker compose logs -f app
```

访问 `http://localhost:8000`。`compose.yaml` 将 `data/` 和 `embedding/` 挂载到容器，PostgreSQL 使用独立持久化卷，通过服务名 `db` 连接，无需占用本机数据库端口。此数据库卷与原 `start.bat` 使用的数据库独立，已有数据库内容需另行迁移。

更新时再次执行 `docker compose pull` 和 `docker compose up -d`；停止使用 `docker compose down`。可通过 `.env` 中的 `SCHOLARFLOW_IMAGE` 指定历史镜像标签。未下载 BGE-M3 时页面和文献管理接口仍可启动，语义检索和文献处理需准备模型后重启 `app`。

以下为原有本地 Python 运行方式。

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

### LLM 后端（四选一）

| 方式 | 配置 | 适用场景 |
|---|---|---|
| **Ollama 本地** | 安装 Ollama + `ollama pull qwen3:8b` | 离线使用，无需 API Key |
| **DeepSeek 云端** | `.env` 中设置 `LLM_BACKEND=deepseek` + `CLOUD_API_KEY` | 更快响应，无本地显存要求 |
| **OpenAI 云端** | `.env` 中设置 `LLM_BACKEND=openai` + `CLOUD_API_KEY` | 使用 GPT 系列模型 |
| **Qwen 百炼** | `.env` 中设置 `LLM_BACKEND=qwen` + `CLOUD_API_KEY` | 阿里云通义千问 API |

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

复制 `.env.example` 为 `.env`，用文本编辑器打开修改：

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

### 核心接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/health` | 健康检查（含 LLM/Embedding 状态） |
| `GET` | `/stats` | 数据库统计（文献/切片/化合物/谱图） |
| `POST` | `/search` | 跨源文献检索（8 数据源，支持自然语言+作者+期刊过滤） |
| `POST` | `/search/stream` | 流式检索（SSE 实时进度推送） |
| `POST` | `/translate` | 英文摘要翻译为中文 |
| `POST` | `/ask` | RAG 问答（基于本地文献库） |
| `POST` | `/review` | 文献综述生成 |
| `POST` | `/chunks/search` | 检索文本块（不调用 LLM） |
| `POST` | `/rag/warmup` | 预热 embedding + FAISS 索引 |

### 文献库管理

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/papers` | 文献库列表（支持分页/状态/评分过滤） |
| `GET` | `/papers/{id}` | 文献详情（完整元数据 + 处理状态） |
| `GET` | `/papers/{id}/text` | 文献全文（chunks 拼接） |
| `GET` | `/papers/{id}/pdf` | 下载 PDF 原文 |
| `GET` | `/papers/{id}/chunks` | 文本块列表 |
| `POST` | `/papers/import` | 文献入库（仅 metadata） |
| `POST` | `/papers/upload-pdf` | 独立上传 PDF 入库（自动触发流水线） |
| `POST` | `/papers/{id}/process` | 触发后台流水线（下载→解析→切块→索引） |
| `POST` | `/papers/{id}/upload-pdf` | 为已有文献上传 PDF |
| `DELETE` | `/papers/{id}` | 删除文献（含数据库记录+本地文件） |

### Agent 对话

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/agent/chat` | Agent 对话（多轮记忆，7 工具自动调度） |
| `GET` | `/agent/sessions` | 会话列表 |
| `GET` | `/agent/sessions/{id}` | 会话详情（完整消息历史） |
| `DELETE` | `/agent/sessions/{id}` | 删除会话 |

### 管理工具

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/admin/clear-sessions` | 清空所有 Agent 会话 |
| `POST` | `/admin/clear-all` | 清除全部数据（文献+PDF+索引+会话，不可恢复） |

### 处理流水线

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/pipeline/crawl-literature` | 采集文献 metadata（多数据源+去重+评分） |
| `POST` | `/pipeline/download-pdfs` | 批量下载开放获取 PDF |
| `POST` | `/pipeline/parse-pdfs` | 批量解析 PDF → 结构化 JSON |
| `POST` | `/pipeline/build-chunks` | 批量构建文本块 |
| `POST` | `/pipeline/build-index` | 批量向量化 + FAISS 索引构建 |

---

## 数据源

| 数据源 | 后端 | 说明 |
|---|---|---|
| Europe PMC | Europe PMC REST API | 通用生物医学（Nature/Science/Cell 底层也走此 API） |
| PubMed | NCBI E-utilities API | MEDLINE 文献，含 MeSH 主题词和 Publication Type |
| Semantic Scholar | S2 Graph API | 通用学术搜索，2 亿+ 论文 |
| arXiv | arXiv API | 预印本 |
| OpenAlex | OpenAlex REST API | 跨学科学术搜索，2.5 亿+ 作品，含引用计数 |
| Nature | Europe PMC + 期刊过滤 | Nature 系列期刊 |
| Science | Europe PMC + 期刊过滤 | Science 系列期刊 |
| Cell | Europe PMC + 期刊过滤 | Cell Press 期刊 |

---

## Agent 工具

| 工具 | 说明 |
|---|---|
| `search_papers` | 跨源检索论文（支持自然语言 + 作者名筛选，中文名自动拼音扩展） |
| `list_library` | 查看本地已入库文献列表 |
| `view_paper` | 查看库中论文全文 |
| `ask_paper` | RAG 问答（基于本地文献库） |
| `write_review` | 撰写文献综述 |
| `web_search` | 网页搜索引擎（DuckDuckGo），补充学术 API 覆盖不到的来源 |
| `import_paper` | 将论文导入本地文献库（Agent 可直接入库） |

### 搜索深度

| 模式 | 说明 |
|---|---|
| **深度搜索（deep）** | 返回完整 metadata 表格（标题/作者/年份/期刊/DOI），搜索后主动提供入库建议 |
| **快速搜索（quick）** | 仅返回标题和年份，回复简洁 |

### 中文作者名自动扩展

输入中文名（如"张爽"）时，自动生成 8 种英文拼音变体并发起 OR 查询：

```
Shuang Zhang / Zhang Shuang / ZhangShuang / Zhangshuang /
shuangzhang / zhangshuang / ShuangZhang / Shuangzhang
```

英文名（如"Hinton"）不做扩展，直接精确查询。

---

## 数据目录

```
data/
├── sessions.json    # Agent 对话会话持久化
├── index/           # FAISS 向量索引 + chunk 元数据
├── papers/          # 下载的 PDF 原文
├── pdfs/            # 手动上传的 PDF 文件
├── texts/           # PDF 解析后的结构化 JSON
├── compounds/       # 化合物数据（预留）
├── spectra/         # 谱图数据（预留）
└── db/              # 数据库文件（预留）
```

---

## 技术架构

```
用户 → React 前端 → FastAPI 后端
                      ├── LangChain Agent
                      │   ├── search_papers / list_library
                      │   ├── view_paper / ask_paper / write_review
                      │   ├── web_search / import_paper
                      │   └── LLM: Ollama / DeepSeek / OpenAI / Qwen 可切换
                      ├── 文献采集层（8 数据源，并行检索）
                      ├── 文档处理层（PDF 解析 → 切块）
                      ├── RAG 引擎（BGE-M3 + FAISS）
                      ├── 配置管理（.env + 运行时校验）
                      └── PostgreSQL 存储
```

| 层级 | 技术 |
|---|---|
| 后端 | FastAPI + SQLAlchemy async + asyncpg |
| 前端 | React 18 + TypeScript + Vite + Tailwind CSS |
| LLM | Ollama (qwen3:8b) / DeepSeek (deepseek-chat) / OpenAI / Qwen 百炼 |
| Embedding | BGE-M3 (sentence-transformers)，启动后台预热，~6s 就绪 |
| 向量检索 | FAISS (CPU) |
| Agent | LangChain create_agent + 7 tools（含 web_search / import_paper） |
| 网页搜索 | DuckDuckGo（ddgs），零配置免费使用 |
| 中文拼音 | pypinyin，自动扩展中文作者名为 8 种英文变体 |
| 文献源 | Europe PMC / PubMed / Semantic Scholar / arXiv / OpenAlex / Nature / Science / Cell |
| 数据库 | PostgreSQL 16 (Docker) |
| PDF 解析 | PyMuPDF |

---

## 项目结构

```
ScholarFlow/
├── app/
│   ├── agent/                    # LangChain Agent
│   │   ├── agent.py              # Agent 工厂 + 会话管理 + 搜索深度
│   │   ├── tools.py              # 7 个 Tool 定义
│   │   ├── keyword_extractor.py  # LLM 关键词提取
│   │   ├── web_search.py         # DuckDuckGo 网页搜索
│   │   └── name_utils.py         # 中文作者名拼音扩展
│   ├── harvest/                  # 文献采集层
│   │   ├── harvester.py          # 采集总控（并行检索+去重+评分）
│   │   └── literature/           # 8 个数据源客户端
│   │       ├── europe_pmc_client.py
│   │       ├── pubmed_client.py
│   │       ├── semantic_scholar_client.py
│   │       ├── arxiv_client.py
│   │       ├── openalex_client.py
│   │       ├── nature_client.py
│   │       ├── science_client.py
│   │       └── cell_client.py
│   ├── document/                 # PDF 解析 + 章节识别 + 切块
│   ├── domain/                   # 语义评分（查询驱动）+ 论文标签
│   ├── rag/                      # RAG 引擎（embedding+检索+生成）
│   ├── services/                 # 业务服务层
│   ├── storage/                  # 数据库 ORM + 文件存储 + 仓库
│   ├── api/                      # 流水线路由
│   ├── config.py                 # 配置管理（.env 加载+校验）
│   ├── llm_factory.py            # LLM 工厂（ollama/deepseek/openai/qwen）
│   └── main.py                   # FastAPI 入口（30+ 端点）
├── frontend/                     # React 前端
│   └── src/
│       ├── pages/                # 6 个页面
│       ├── components/           # 通用组件 + 流水线进度
│       ├── hooks/                # React Query hooks
│       └── lib/                  # API 调用层 + 类型定义
├── scripts/                      # 命令行工具（10 个脚本）
├── requirements/                 # GPU 分架构依赖文件
├── embedding/                    # BGE-M3 本地模型
├── data/                         # 运行时数据
├── start.bat                     # 一键启动
├── install_deps.bat              # GPU 智能依赖安装
└── .env                          # 环境配置
```

---

## 常见问题

**Q: 启动后白屏？** 按 `Ctrl+Shift+R` 强制刷新浏览器。

**Q: 修改前端代码后没变化？** 执行 `cd frontend && npm run build` 重新构建。

**Q: 如何切换 LLM？** 修改 `.env` 中 `LLM_BACKEND`（`ollama` / `deepseek` / `openai` / `qwen`），重启服务。

**Q: 检索很慢？** 已优化为多源并行检索 + GPU embedding。8 个源约 5~8 秒。
