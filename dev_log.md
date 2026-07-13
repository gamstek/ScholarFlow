# 项目开发日志

## 项目概述

### 目标

构建一个通用型文献采集 Agent，支持官网优先、API 兜底的混合采集通道，并预留少量可配置接口，便于后续快速迁移到任意细分领域。

### 输入

领域关键词、目标期刊或来源列表、官网页面与公开 API 返回的文献元数据、摘要、开放获取信息以及可用的全文链接。

### 输出

统一结构的文献记录、采集状态与错误信息、可复用的采集接口，以及面向用户的本地前端工作台。

### 方法介绍

采用可插拔采集适配器与统一归一化流程，将不同来源的文献信息标准化入库；同时保留领域配置入口，支持后续按需调整采集范围与过滤策略。

---

## 开发时间线

### 2026-07-13

重构(embedding): 新建 embedding/ 本地模型目录，统一全项目 BGE-M3 路径解析

- 新建 `embedding/` 目录 + `README.md`（含手动下载 BGE-M3 的三种方法和目录结构说明）。
- `app/rag/embedder.py` 新增 `_resolve_embedding_model_path()` 统一路径解析：优先级为 `BGE_MODEL_PATH` 环境变量 → `embedding/bge-m3/` 本地目录 → `BAAI/bge-m3` HF Hub 回退。
- 导出模块级常量 `DEFAULT_EMBEDDING_MODEL`，全项目 8 个文件统一引用该路径，消除所有硬编码 `"BAAI/bge-m3"`：
  - `app/rag/embedder.py` — `TextEmbedder.DEFAULT_MODEL`
  - `app/rag/rag_engine.py` — `LocalRagEngine.__init__` 默认参数
  - `app/rag/retriever.py` — `LocalChunkRetriever.__init__` 默认参数
  - `app/domain/filters.py` — `QueryDrivenScorer.DEFAULT_MODEL`
  - `app/main.py` — lifespan 预热 + 3 个 Pydantic Request 模型的 default
  - `app/api/pipeline_routes.py` — `BuildIndexRequest.model_name` default
  - `app/services/pipeline_service.py` — `build_faiss_index_service` 默认参数
  - `app/agent/tools.py` — `ask_paper` Tool 内 `LocalRagEngine` 初始化
  - `scripts/06_build_index.py` / `scripts/08_search.py` / `scripts/09_ask.py` — 命令行参数 default
- `.env` 中 `BGE_MODEL_PATH` 改为 `embedding/bge-m3`（相对项目根目录）。

文档生成(README): 按"环境要求→检测→依赖准备→.env配置→启动"流程重排 README

- 新增"1. 环境要求"小节（硬件/软件/LLM 后端/Embedding 模型，含 BGE-M3 本地下载命令）。
- 新增"2. 环境检测"小节（`check_env.py` 检测项说明）。
- 将原"快速开始"拆分为"3. 依赖准备"（3.1 conda 环境 → 3.2 install_deps.bat → 3.3 下载 BGE-M3 → 3.4 Docker PostgreSQL → 3.5 Ollama 模型）。
- "4. .env 配置"更新 `BGE_MODEL_PATH=embedding/bge-m3`，补充 `openai`/`qwen` 后端说明。
- "5. 启动"增加 `start.bat` 自动完成的 5 个步骤说明。
- 保留 API 接口/数据源/Agent 工具/数据目录/技术架构/项目结构/常见问题不变。

### 2026-07-10

代码生成(harvester+frontend): 检索结果增加按时间/引用量排序 + SSE 流式检索进度显示

- 后端 `PaperMetadata` / `SearchHit` / `Paper` 模型增加 `citation_count` 字段。
- 新增 `parse_citation_count()` 共享解析函数，Europe PMC / Nature / Science / Cell 四个源统一解析 `citedByCount`（均经 Europe PMC 底层 API）。
- Semantic Scholar 增加 `citationCount` 到请求字段并解析。
- `search_only` 新增 `sort_by` 和 `sort_order` 参数。
- 新增 `search_only_stream` 异步生成器 + `POST /search/stream` SSE 端点。
- 前端新增排序按钮组 + 进度条 + 客户端重排。

性能优化(harvester): 多源并行查询 + embedding 预热 + GPU 加速

- `search_only` / `search_only_stream` 的源采集从串行 `for` 改为 `asyncio.gather` + `asyncio.to_thread` 并行。
- `search_only_stream` 用 `asyncio.as_completed` 确保先完成的源先推送进度。
- FastAPI `lifespan` 启动时预热 BGE-M3 embedding 模型，首次搜索省 10s。
- BGE-M3 批量编码 60 篇仅 0.11s（RTX 4060 GPU）。

代码生成(frontend): 论文卡片点击查看元数据 + 摘要翻译

- 检索结果卡片可点击，弹出模态框展示标题/作者/年份/期刊/DOI/来源/摘要。
- 英文摘要自动调用 `/translate` API 翻译为中文（支持 deepseek 和 Ollama）。
- 模态框点击遮罩层或 X 按钮关闭，卡片内按钮 `stopPropagation` 防误触。

代码生成(agent): Agent 支持云端 API (deepseek)

- `get_agent()` 读取 `LLM_BACKEND` 环境变量，`deepseek` → `ChatOpenAI`（兼容 DeepSeek API），`ollama` → `ChatOllama`。
- 解决 Agent 始终使用 Ollama 而忽略 `.env` 配置的问题。

代码生成(agent): 新增 list_library 工具 + 会话持久化

- 新增 `list_library` Tool，直接查询本地数据库返回已入库文献列表。
- `SessionManager` 增加文件持久化（`data/sessions.json`），服务重启不丢失对话。
- Agent 系统提示词更新，引导优先使用 `list_library` 查本地库。

修复(startup): start.bat 双击闪退

- `start.bat` 换行符为 LF（Unix）导致 cmd.exe 解析含括号块的 `if` 语句崩溃，转为 CRLF。

修复(frontend): 检索进度条和排序按钮不显示

- 进度条和排序按钮被嵌套在 `{result && (...)}` 条件块内，检索开始时 `result=null` 不渲染 → 移到外部。

修复(frontend): Agent 历史对话点击白屏

- 会话 `tool_calls[].input` 为 JSON 对象时 React 直接渲染报 Error #31 → 序列化为字符串。

修复(frontend): 关闭网页后再打开检索结果丢失

- SearchPage 增加 `localStorage` 持久化，保存/恢复检索结果和排序参数。

修复(frontend): 左下角模型显示与实际不同步

- `/health` 端点硬编码 Ollama → 改为读取 `LLM_BACKEND`，deepseek 显示 `deepseek-chat`。

修复(backend): Agent 调用 search_papers 时 event loop 冲突

- `async_engine` 连接池绑定 uvicorn 循环，`asyncio.run()` 新建循环冲突 → 池改为 `NullPool`。

修复(frontend): 前端白屏（index.html 缓存）

- `FileResponse` 无 cache header，浏览器缓存旧 HTML 引用已删除的 JS → 加 `Cache-Control: no-cache`。

修复(startup): 启动时打开两个浏览器标签

- `main.py` 和 `start.bat` 各开一个 → 删除 `main.py` 中的 `webbrowser.open`。

重构(frontend): 暂时隐藏引用量排序

- 前端排序选项去掉"引用量"和"被引 X 次"显示，后端数据采集保留不动。

调试(arxiv): arXiv 连接问题排查

- SSL 证书链、频率限制、网络环境均正常。`CERT_NONE` 绕过已多余。

其他(data): 清洗 data/ 目录

- 删除孤立 text 文件（无对应 DB 记录）、诊断 JSON、空目录（compounds/db/pdfs/spectra/test）。

修复(dependencies): requirements 缺失 langchain-openai 导致 Agent 启动报错

- 三个 `requirements-rtx*.txt` 的 LangChain Agent 区块均缺少 `langchain-openai>=0.3`，导致 `agent.py` 顶层 import 失败（`ModuleNotFoundError: No module named 'langchain_openai'`）。
- 已补入三个文件并在 scholarflow 环境安装（langchain-openai 1.3.4 + openai 2.45.0 + tiktoken 0.13.0）。
- 同时修正 `start.bat` 硬编码的 Python 路径（`D:\Anaconda3\...` → `C:\Users\HP\.conda\...`）。

文档生成(README): 补充 BGE-M3 下载缓存说明 + .env 配置指引

- Embedding 模型区块：新增首次下载说明（模型大小 ~2.2GB、缓存路径、国内镜像 `hf-mirror.com`、HF_HUB_OFFLINE 开关时机）。
- .env 配置区块：从"可选"改为"按需修改"，补充 `DATABASE_URL`、`HF_HUB_OFFLINE` 等完整字段说明，明确只需改一行即可切换 LLM。

代码生成(startup+README): start.bat 修复 .env 解析 + README 添加 Docker 数据库容器教程

- `start.bat` 的 `.env` 解析用 `findstr /v "^#"` 过滤注释行 + `findstr "."` 过滤空行 + `tokens=1*` 保留值中的 `=`，避免注释行被当作变量赋值导致异常。
- `README.md` 新增"0. 创建数据库容器"小节，含 `docker run` 完整命令、验证/启停命令，与 `.env` 参数对应说明。

### 2026-07-09

需求分析(依赖管理): RTX 30/40/50 系列 GPU 多架构依赖分拆

- 根因：不同 GPU 架构的 CUDA compute capability 不同——30 系 (SM 8.6, CUDA 11.x/12.1)、40 系 (SM 8.9, CUDA 12.4)、50 系 (SM 12.0, 必须 CUDA ≥12.8)。单一 `requirements.txt` 硬编码 `torch==2.11.0+cu128` 仅适用 50 系。
- 新建 `requirements-rtx30.txt`（CUDA 12.1, torch 2.5.1+cu121）、`requirements-rtx40.txt`（CUDA 12.4, torch 2.5.1+cu124）、`requirements-rtx50.txt`（CUDA 12.8, torch 2.11.0+cu128），统一放入 `requirements/` 文件夹。
- 三个文件除 PyTorch CUDA build 外，其余依赖完全一致（FAISS 统一用 CPU 版，避免跨 CUDA 版本冲突）。
- 主 `requirements.txt` 移入 `requirements/` 文件夹，新增 GPU 选择指南注释 + 保留 RTX 50 系内容（当前开发机）。
- 新建 `install_deps.bat` 智能安装脚本：nvidia-smi 自动检测 GPU 型号 → 匹配 compute capability → 选择对应依赖文件 → pip 安装 → torch.cuda.is_available() 验证。
- 覆盖型号名检测（RTX 50/40/30 关键字匹配）+ compute capability 兜底（12.x → 50 系, 8.9 → 40 系, 8.6 → 30 系）+ 手动选择三级回退。
- 兼容 conda 环境和系统 Python，自动识别当前激活的 conda env 并透传 pip install。
- 结果：项目依赖从单一 RTX 50 扩展至全系列 30/40/50 GPU，安装即匹配。

其他(Skill): 新增 code-change-logger 代码修改记录技能

- 创建 `.github/skills/code-change-logger/SKILL.md`，定义自动触发的代码改动记录工作流。
- 每次编辑工具调用后自动询问改动人，记录时间（YY-MM-DD）、类型（新增/删除/调整/重构/修复/优化）、说明（文件:行号+联动）、内容（精简说明）、理由到 `docs/Modified.md`。
- 创建 `docs/Modified.md` 初始模板，按日期分组、当日内编号递增。
- 与 `dev-log-writer` 互补：`dev_log.md` 记录任务级功能，`docs/Modified.md` 记录改动级代码细节。
- 来源：用户要求创建自动化代码改动追踪 skill。

### 2026-07-08

调试(启动优化): HF_HUB_OFFLINE + IPv6 + local_files_only 三连修复

- 根因：sentence-transformers 每次加载 BGE-M3 前向 HF Hub 发 10+ HEAD 请求验证缓存，HF 不可达时超时 60-120s。
- `.env` 新增 `HF_HUB_OFFLINE=1`；`start.bat` 同步设置；`embedder.py` 中 `SentenceTransformer()` 补充 `local_files_only=True`。
- `DATABASE_URL` 中 `localhost` 在 WSL2 下先解析为 IPv6 `::1`，超时 5s 后才回退 IPv4 → 改为 `127.0.0.1`。
- 启动时间从 60-120s 降至 5-10s。

修复(兼容性): langchain + transformers 版本冲突

- `langchain==1.3.11` 旧 API `AgentExecutor`/`create_react_agent` 已移除 → 迁移至 `create_agent`（langchain >= 1.0 API）。
- `torch==2.5.1+cu124` < 2.6 与 `transformers==5.12.1` 冲突 → 降级 `transformers==4.48.3`。

调试(环境): Docker + Python 环境修复

- Docker `scholarflow-pg` 容器手动启动，端口映射 `5433→5432`（本机两个 PG 实例避免冲突）。
- 11 处硬编码路径统一改为 `"BAAI/bge-m3"`。
- 创建 `.env` 文件并接入 `load_dotenv()`。

### 2026-07-03

功能(文献库管理): 删除文献 + 查看源数据

- 新增 `PaperRepository.delete_paper()` 方法，通过 ORM 删除 paper（数据库级联删除 chunks）。
- 新增 `DELETE /papers/{paper_id}` 端点，删除数据库记录 + 本地 PDF + 本地文本文件，返回确认信息。
- 前端 api.ts 新增 `api.deletePaper()`，Paper 类型扩展 `pmid`/`pmcid`/`source`/`url`/`pdf_url`/`license`/`created_at`/`updated_at` 等字段。
- usePapers hook 新增 `deletePaper` mutation，删除后自动刷新 papers 和 stats 缓存。
- LibraryPage 每条文献行新增**查看源数据**按钮（眼睛图标），点击展开 SourceDataView 组件，显示 DOI、PMID、作者、摘要、许可证等完整元数据。
- LibraryPage 每条文献行新增**删除**按钮（垃圾桶图标），带确认对话框，确认后删除文献及本地 PDF（不可恢复）。
- 表头 ID 列改为序号列（1, 2, 3...），数据库 ID 移至源数据视图内显示。
- 结果：文献库支持完整的增删查管理流程，源数据一键查看。

修复(前端): 刷新按钮 + ID 列显示

- 刷新按钮 spinner 状态从 `isLoading` 改为 `isFetching`，解决刷新时无视觉反馈的问题。
- 文献列表 ID 列改为按位置计算的序号，删除条目后序号自动连续。

其他(启动脚本): start.bat 移除前端构建步骤

- 移除 `npm install && npm run build` 步骤，启动流程从 4 步简化为 3 步。
- 原因：Node.js/npm 安装在 Trae IDE 私有路径下，不在系统 PATH，双击 start.bat 时无法找到 npm，构建步骤形同虚设。
- 前端已预构建在 `frontend/dist/` 中。如需修改前端代码，在 Trae IDE 终端中执行 `cd frontend && npm run build`。

其他(文档): 更新 README.md

### 2026-07-02

需求分析(跨机器移植): 项目兼容性审计 + 可移植部署方案设计

- 完成 28 个源文件的 GPU/CUDA/路径硬编码全量审计。
- 设计宿主机 PyTorch 直接 GPU 访问 + Docker 仅跑 PostgreSQL 的混合架构。
- 覆盖 RTX 3050~5090 全部系列的显存/架构/PyTorch/Ollama 推荐矩阵。
- LLM 后端设计为策略模式（OllamaBackend + OpenAICompatibleBackend），.env 切换。

文档生成(移植指南): 重写 `移植.md` 为 14 章完整手册

- 含 `.env.example` 模板、`setup.py` GPU 检测代码、`llm_backend.py` 完整实现。
- `docker-compose.yml` + `database.py` SQLite 回退代码。
- 结果：从操作手册升级为完整部署方案文档。

### 2026-07-01

重构(数据库): SQLite → PostgreSQL + SQLAlchemy async 迁移

- 新增 `app/storage/models.py`，6 张表改用 SQLAlchemy DeclarativeBase 定义。
- 重写 `app/storage/database.py`，异步引擎 `asyncpg` + 连接池 `pool_size=20`。
- 重写 `app/storage/repositories.py`，所有方法改为 `async def`，upsert_paper 增加状态优先级字典。
- 新增 `get_connection()` 同步兼容层，桥接尚未迁移的调用方。
- main.py 启动方式从 `@app.on_event` 改为 `lifespan`。
- 原因：SQLite 无法支撑大规模文献数据和并发读写，同步调用会阻塞 FastAPI event loop。
- 结果：PostgreSQL Docker 容器运行正常，init_db + CRUD 验证通过。

重构(命名): 领域通用化——清理所有 food 相关硬编码

- 项目名 `lit-agent` / `Food Structure RAG` → `ScholarFlow`，版本号 `0.1.0` → `0.2.0`。
- `FoodLiteratureHarvester` → `LiteratureHarvester`，同步更新 harvester.py / pipeline_service.py / crawl_literature.py。
- `food_keywords.py` → `keywords.py`，`food_filters.py` → `filters.py`，更新所有 import。
- `crawl_food_literature.py` → `crawl_literature.py`，`test_food_filters.py` → `test_filters.py`。
- `build_food_structure_query` → `build_enhanced_query`，支持可配置 `enhance_terms` 参数。
- `EuropePmcClient` user_agent `FoodStructureRAG/0.1` → `ScholarFlow/0.2`。
- System prompt 从"食品成分结构分析"改为"科研文献 RAG 助手"。
- index.html 文案从"面向食品成分结构文献工作"改为"通用文献采集与检索智能体"。
- 结果：项目已从单一食品领域解耦，可按需配置为任意研究方向。

重构(BGE模型): 硬编码本地模型路径

- 所有加载 BGE-M3 的位置（embedder.py / retriever.py / rag_engine.py / main.py / pipeline_routes.py / 3 个脚本 / app.js）统一改为本地绝对路径。
- 路径: `C:/Users/Admin/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181`
- 原因：避免每次从 HuggingFace Hub 下载（约 4GB），且解决之前缓存不完整导致的加载失败。
- 结果：模型加载全程离线，dim=1024 验证通过。

其他(修复): P2 健壮性修复 + 项目状态检查

- retriever.py: `vector_store.load()` → `load_or_create()`，避免首次未建索引 500。
- pipeline_service.py: `download_open_access_pdfs_service` 去除 `list_candidate_papers` 重复查询。
- 全项目导入检查：所有 20 个 app/ 模块导入通过。
- 更新 `v0.1.0_项目总结.md` 为 `v1.0.0`，同步 dev_log 格式规范。

### 2026-06-26

其他(空文件): 补齐 6 个空文件骨架

- `app/agent/literature_agent.py` — LiteratureAgent 占位类。
- `app/agent/task_planner.py` — plan_tasks() 占位函数。
- `app/agent/report_writer.py` — write_report() 占位函数。
- `app/harvest/literature/crossref_client.py` — CrossrefClient 骨架。
- `scripts/evaluate_retrieval.py` — main() 占位。
- `scripts/build_index.py` — 引导至 build_faiss_index_from_chunks.py。
- 原因：6 个文件完全为空，避免 import 静默通过、运行时才发现缺失。
- 结果：全部导入正常，raise NotImplementedError 验证通过。

### 2026-06-25

需求分析(项目定位): 将项目目标从单一食品领域调整为通用型文献采集 Agent

- 确认采用官网优先、API 兜底的混合采集通道，并保留后续领域微调接口。
- 结果：项目 charter 更新为 domain-neutral 方向。

其他(开发日志): 将历史日志统一收拢至 dev_log.md

- 已将 logw1.md 与 logw2.md 的内容整合进正式开发日志，两个旧文件已移除。
- 原因：按项目规范只保留单一 dev_log.md。

### 2026-06-06

数据建模(pdf_resolver): 实现开放获取 PDF 批量下载

- 新增 `scripts/download_open_access_pdfs.py`，支持从 SQLite 筛选 OA 文献并按数量批量下载 PDF 到 `data/papers/`。
- 新增 `app/harvest/literature/pdf_resolver.py`，封装 PDF 地址识别与下载能力，区分单篇/批量接口。
- 下载完成后同步更新 `papers.local_pdf_path` 和状态。
- 结果：OA PDF 批量下载流程跑通，候选筛选、下载回写均正常。

代码生成(pdf_parser): 实现 PDF 正文提取与清洗

- 新增 `app/document/pdf_parser.py`，使用 PyMuPDF 按页提取文本并做温和清洗（修复英文断词换行、删除多余空行）。
- 输出 `ParsedPdfPage` / `ParsedPdfDocument` 结构化结果。
- 原因：为后续章节识别和 chunk 切分提供干净的文本输入。

代码生成(section_parser): 实现规则版论文章节识别

- 新增 `app/document/section_parser.py`，识别 Abstract / Introduction / Methods / Results / Discussion / Conclusion 等常见章节。
- 采用规则匹配策略，对 LC-MS/MS、样品前处理等食品论文常见小节做额外兼容。
- 结果：规则版解析足以支撑 V0 阶段的正文结构化处理。

代码生成(check_paper_status): 实现数据库论文状态检测脚本

- 新增 `scripts/check_paper_status.py`，快速查看每篇论文的处理进度（metadata_only / pdf_downloaded / parsed / chunked / indexed）。
- 原因：下载成功不等于解析成功，需要可视化各环节状态以定位异常。

其他(进度总结): V0 基础链路阶段性总结

- 已完成：SQLite 数据底座 → 领域过滤器 → Europe PMC 接入 → OA PDF 下载 → PDF 正文提取 → 章节识别 → 状态检查。
- 下一步：chunk 切分、向量索引构建、RAG 问答。

### 2026-06-05

数据建模(database): 搭建 SQLite 数据底座

- 新增 `app/storage/database.py`，定义项目数据目录和 6 张核心表：crawl_tasks / papers / chunks / compounds / spectra / paper_compound_links。
- 新增 `app/storage/models.py`，用 dataclass 定义 CrawlTask / Paper / Chunk / Compound / Spectrum / PaperCompoundLink。
- 新增 `app/storage/repositories.py`，封装数据库读写逻辑，统一处理任务、文献、chunk 等数据访问。
- 新增 `scripts/init_db.py`，支持一键初始化数据库并插入测试数据验证可用性。
- 结果：数据库骨架搭建完成，初始化脚本正常，外键约束可用。

代码生成(food_filters): 实现食品成分结构分析领域过滤器

- 新增 `app/domain/food_keywords.py`，按类别维护关键词：食品来源、食品成分、结构分析、质谱方法、组学、强相关词、排除词。
- 新增 `app/domain/food_filters.py`，实现多维度规则型领域过滤，综合判断标题、摘要、期刊、关键词。
- 设计加权评分机制（核心维度各 0.20，辅助维度各 0.10），命中排除词扣分，输出 0-1 的 domain_score。
- 保留规则：同时命中“食品/成分”和“结构/质谱”的文章更容易保留。
- 原因：规则法适合当前阶段，便于解释和手动微调；多维度组合判断兼顾召回率和准确率。

代码生成(europe_pmc): 接入 Europe PMC 真实数据源

- 新增 `app/harvest/literature/europe_pmc_client.py`，封装检索能力，拿回标题、摘要、DOI、PMID、PMCID 等 metadata。
- 新增 `app/harvest/harvester.py`，串起"检索 → 过滤 → 保存"完整流程。
- 新增 `scripts/crawl_food_literature.py`，采集脚本入口，跑真实检索并生成报告。
- 测试结果：10 篇候选 → 领域过滤器保留 8 篇 → 8 篇入库，链路 "检索 → 过滤 → 入库" 跑通。
