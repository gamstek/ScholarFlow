# ScholarFlow

> 个人文献工作站 — 智能采集、语义检索、RAG 问答、文献综述，一站式本地运行。

---

## 功能概览

| 功能 | 说明 |
|---|---|
| **智能检索** | 输入一句话，LLM 自动提取关键词+领域，多源检索并评分，结果标注在库状态 |
| **一键入库** | 库外论文点击入库，后台自动完成 PDF 下载→解析→切块→索引 |
| **论文查看器** | 在线阅读全文（文本/PDF 双模式），显示本地存储路径 |
| **文献库管理** | 查看所有入库文献及处理状态，支持查看源数据、上传 PDF、删除文献 |
| **RAG 问答** | 对本地文献库提问，基于检索证据回答，附带引用来源 |
| **文献综述** | 输入主题，自动检索相关文献并生成结构化 Markdown 综述 |
| **Agent 对话** | 自然语言对话，Agent 自动决策调用检索/查看/问答/综述工具 |

---

## 环境要求

### 必需依赖

| 依赖 | 版本 | 说明 |
|---|---|---|
| **Python** | 3.10 ~ 3.12 | 后端运行环境 |
| **Node.js** | 18+ | 前端构建（仅修改前端代码时需要） |
| **PostgreSQL** | 16+ | 文献数据存储 |
| **Ollama** | 最新 | 本地 LLM 服务 |

### Ollama 模型

启动 Ollama 后拉取模型：

```bash
# 生成模型（RAG 问答、综述、关键词提取）
ollama pull qwen3:8b

# 如果显存不够，可用更小的模型
ollama pull qwen2.5:3b
```

### Embedding 模型

项目使用 BGE-M3 嵌入模型，首次运行时自动下载到 HuggingFace 缓存目录。
如需离线使用，可提前下载：

```bash
pip install sentence-transformers
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"
```

---

## 环境检测

在开始之前，运行一键检测脚本确认本机环境是否满足要求：

```bash
# 终端文本报告
python .github/skills/check-dependencies/check_env.py

# JSON 格式（供脚本解析）
python .github/skills/check-dependencies/check_env.py --json

# 图形弹窗（推荐，支持一键修复）
python .github/skills/check-dependencies/check_gui.py
```

检测覆盖以下项目：

| 类别 | 检测内容 |
|------|---------|
| Conda | 当前环境是否为 `scholarflow` |
| Python | 版本是否在 3.10 ~ 3.12 范围内 |
| pip | 全部依赖包版本是否匹配 `requirements.txt` |
| PyTorch | 安装状态 + CUDA/GPU 架构匹配 |
| Ollama | 服务是否运行 + 已安装的 LLM 模型 |
| PostgreSQL | 数据库连接可用性 |
| FAISS | 向量索引文件是否存在 |
| 嵌入模型 | sentence-transformers 是否安装 |
| 磁盘 | 可用空间 ≥ 2GB |

检测通过后，按下方步骤继续。

---

## 快速开始

### 首次使用准备（只需做一次）

#### 1. 安装 Docker Desktop

下载安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/) 并启动。

#### 2. 安装 Ollama

下载安装 [Ollama](https://ollama.com/)，然后在命令行执行：

```bash
ollama pull qwen3:8b
```

等待模型下载完成（约 5GB）。

#### 3. 安装 Node.js

下载安装 [Node.js 18+](https://nodejs.org/)（用于前端构建）。

### 日常使用（每次启动只需一步）

**双击 `start.bat`**

脚本会自动完成以下全部工作：

```
[1/3] Checking database...        ← 自动启动 Docker 中的 PostgreSQL
[2/3] Checking Ollama...          ← 自动启动 Ollama
[3/3] Starting ScholarFlow...     ← 启动后端 + 自动打开浏览器
```

浏览器会自动打开 http://localhost:8000，直接开始使用。

**停止服务**：在命令行窗口按 `Ctrl+C`。

> 前端已预构建在 `frontend/dist/` 中。如需修改前端代码，在终端中执行 `cd frontend && npm run build` 重新构建。

---

## 使用指南

### 1. 文献检索

- 切换「自然语言」模式，直接用中文描述需求，例如：*我想找母乳低聚糖结构鉴定的文章*
- LLM 自动提取英文关键词和领域标签
- 检索结果展示：评分、DOI 链接、在库状态
- 库外论文点击「入库」按钮，自动触发后台流水线
- 库内论文点击「查看论文」直接打开论文查看器

### 2. 文献库

- 查看所有入库文献列表，包含标题、年份、处理状态、本地路径、评分
- **查看源数据**：点击眼睛图标展开，查看 DOI、PMID、作者、摘要、许可证等完整元数据
- **上传 PDF**：对于未下载 PDF 的文献，手动上传本地 PDF 文件
- **触发处理**：点击「处理」按钮触发 PDF 下载→解析→切块→索引流水线
- **删除文献**：点击垃圾桶图标，确认后删除文献记录及本地 PDF 文件（不可恢复）
- 统计卡片展示文献总数、文本块数、已索引数、待处理数

### 3. Agent 对话

- 在侧边栏选择「Agent 对话」
- 用自然语言描述需求，Agent 自动选择合适的工具
- 示例：
  - *帮我找关于 CRISPR 基因编辑在农作物改良方面的论文*
  - *对本地文献库提问：HMO 的结构鉴定方法有哪些？*
  - *帮我写一篇关于食品代谢组学的文献综述*

### 4. 论文查看器

- 文本模式：查看解析后的全文（按章节分段）
- PDF 模式：内嵌 PDF 查看器，支持滚动浏览
- 显示本地存储路径（PDF 文件和解析文本的位置）

### 5. RAG 问答

- 输入问题，系统从本地文献库检索相关片段
- LLM 基于检索证据生成回答，附带引用来源

### 6. 文献综述

- 输入综述主题
- 系统检索相关文献片段作为证据
- 生成结构化 Markdown 综述（引言、研究发现、讨论、结论）

---

## API 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/health` | 健康检查（含 Ollama 状态） |
| `GET` | `/stats` | 数据库统计 |
| `POST` | `/search` | 跨源文献检索 |
| `POST` | `/ask` | RAG 问答 |
| `POST` | `/review` | 文献综述生成 |
| `POST` | `/agent/chat` | Agent 对话 |
| `GET` | `/papers` | 文献库列表 |
| `GET` | `/papers/{id}` | 文献详情 |
| `GET` | `/papers/{id}/text` | 文献全文 |
| `GET` | `/papers/{id}/pdf` | 下载 PDF |
| `POST` | `/papers/import` | 文献入库 |
| `POST` | `/papers/{id}/process` | 触发后台流水线 |
| `POST` | `/papers/{id}/upload-pdf` | 为已有文献上传 PDF |
| `POST` | `/papers/upload-pdf` | 独立上传 PDF 入库 |
| `DELETE` | `/papers/{id}` | 删除文献（含本地文件） |

---

## 配置说明

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:scholarflow@localhost:5432/scholarflow` | PostgreSQL 连接字符串 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 服务地址 |
| `OLLAMA_MODEL` | `qwen3:8b` | Ollama 模型名称 |

### 数据目录

运行时数据存储在 `data/` 目录下：

```
data/
├── pdfs/        # 下载的 PDF 原文
├── texts/       # PDF 解析后的结构化 JSON
├── index/       # FAISS 向量索引
├── papers/      # 论文文件（预留）
├── spectra/     # 谱图数据（预留）
└── compounds/   # 化合物缓存（预留）
```

---

## 技术架构

```
用户 → React 前端 → FastAPI 后端
                        ├── LangChain Agent（ReAct）
                        │   ├── search_papers tool
                        │   ├── view_paper tool
                        │   ├── ask_paper tool
                        │   └── write_review tool
                        ├── 文献采集层（6 个数据源）
                        ├── 文档处理层（PDF 解析 → 切块）
                        ├── RAG 引擎（BGE-M3 + FAISS + Ollama）
                        └── PostgreSQL 存储
```

### 技术栈

| 层级 | 技术 |
|---|---|
| 后端 | FastAPI + SQLAlchemy async + asyncpg |
| 前端 | React 18 + TypeScript + Vite + Tailwind CSS + TanStack Query |
| LLM | Ollama (qwen3:8b) |
| Embedding | BGE-M3 (BAAI) |
| 向量检索 | FAISS-cpu |
| Agent | LangChain + langchain-ollama |
| 数据库 | PostgreSQL 16 |
| PDF 解析 | PyMuPDF + pdfplumber |

---

## 数据源

| 数据源 | 说明 |
|---|---|
| Europe PMC | 通用生物医学文献 |
| Semantic Scholar | 通用学术搜索 |
| arXiv | 预印本 |
| Nature | Nature 系列期刊 |
| Science | Science 系列期刊 |
| Cell | Cell Press 期刊 |

---

## 常见问题

### Q: 启动后无法连接数据库？

确保 PostgreSQL 已启动，并创建了 `scholarflow` 数据库和用户：

```sql
CREATE USER scholarflow WITH PASSWORD 'scholarflow';
CREATE DATABASE scholarflow OWNER scholarflow;
```

### Q: LLM 回答为空或很慢？

1. 确认 Ollama 已启动：`curl http://localhost:11434/api/tags`
2. 确认模型已拉取：`ollama list`
3. 显存不足时换用小模型：`ollama pull qwen2.5:3b`

### Q: 检索结果中 PDF 无法下载？

部分文献非开放获取（Non-OA），无法自动下载 PDF。可在文献库中手动上传本地 PDF，或点击 DOI 链接访问原文页面。

### Q: Agent 对话没有调用工具？

Agent 依赖 LLM 的 ReAct 推理能力，qwen3:8b 在复杂场景下可能不稳定。尝试：
- 更明确地描述需求（如「检索」「查看」「写综述」）
- 使用更大的模型

### Q: 如何更新前端代码？

修改 `frontend/src/` 下的代码后，在终端执行 `cd frontend && npm run build` 重新构建，然后重启 `start.bat`。

### Q: 启动时提示 npm 找不到？

不影响使用。前端已预构建在 `frontend/dist/` 中，直接运行即可。npm 只在修改前端源码时需要。

---

## 项目结构

```
ScholarFlow/
├── app/
│   ├── agent/                    # LangChain Agent 层
│   │   ├── keyword_extractor.py  # LLM 关键词提取
│   │   ├── tools.py              # 4 个 Tool 定义
│   │   └── agent.py              # ReAct Agent
│   ├── harvest/                  # 文献采集层
│   │   ├── harvester.py          # 采集总控
│   │   └── literature/           # 6 个数据源客户端
│   ├── document/                 # PDF 解析 + 切块
│   ├── domain/                   # 领域评分
│   ├── rag/                      # RAG 引擎
│   ├── services/                 # 业务服务层
│   ├── storage/                  # 数据库 + 文件存储
│   ├── api/                      # 流水线路由
│   └── main.py                   # FastAPI 入口
├── frontend/                     # React 前端
│   └── src/
│       ├── pages/                # 6 个页面组件
│       ├── components/           # 通用组件
│       ├── hooks/                # TanStack Query hooks
│       └── lib/                  # API 调用层 + 类型定义
├── scripts/                      # 命令行脚本
├── data/                         # 运行时数据（git 忽略）
├── start.bat                     # 一键启动脚本
└── requirements.txt              # Python 依赖
```

---

## License

MIT
