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

### 2026-11-10

代码生成(模型自动准备): 将 BGE-M3 初始化内置到 Compose 启动流程，自动下载与验证缺失模型并持久化复用，失败阻止后端启动，保留中断下载缓存；补充生命周期测试及 CI 真实模型下载、断网复用和后端预热检查，下载源继续遵循 CI 官方源、本地按需镜像的约定；Compose、工作流和 Dockerfile 静态检查通过。

代码生成(依赖安装): 按用户要求清理 scholarflow Conda 环境和前端 node_modules，将安装入口替换为统一镜像脚本，补充 CPU 依赖清单、自动架构选择、前端安装构建和命令预览；已验证各架构命令预览及 CPU PyTorch 镜像可用性，项目服务已停止，依赖未重新安装。

需求分析(容器构建): 用户将本地镜像源重装方案调整为 GitHub CI 构建容器镜像，已还原安装入口和说明并移除新增本地安装脚本，转为准备容器构建和发布工作流。

代码生成(Docker/GitHub Actions): 新增前后端多阶段 CPU 镜像、独立容器依赖清单、Compose 部署配置与 GHCR 发布工作流，通过镜像源安装依赖，发布前检查数据库、首页资源和 API；已通过 Compose 与 Dockerfile 静态检查，准备推送触发 CI。

调试(CI 下载源): 根据用户补充要求，取消使用国内镜像源的首轮构建，将 CI 和 Dockerfile 默认下载地址改为官方源，国内镜像源仅通过本地构建参数按需启用，并同步项目约定与运行说明；工作流、Compose 和 Dockerfile 静态检查通过。

- 验证：GitHub Actions 构建 42767990913 全部通过，依赖导入及 PostgreSQL、首页资源和 API 启动检查成功；已发布 ghcr.io/gamstek/scholarflow 的 latest、master 和 sha-4d16980 标签，并确认远端镜像清单可读取。

其他(本地运行环境): 完成 scholarflow CPU 环境依赖安装、独立 PostgreSQL 数据库初始化、前端构建和 BGE-M3 模型下载，创建待填写密钥的云端 API 本地配置；补充启动脚本的 Conda 路径检测并忽略本地模型文件，后续依赖安装按用户要求使用镜像地址。

- 验证：服务已后台启动，首页、前端静态资源、健康检查及文献库接口均返回 HTTP 200，数据库连接正常，BGE-M3 已在 CPU 上完成预热；云端模型等待填写 API Key。

### 2026-07-28

重构(app, frontend, docs): 全面移除机构（institution）搜索功能

- **原因**：实测发现机构搜索完全不可用——Europe PMC 不返回 affiliations 数据导致 `_filter_by_institution` 全部误杀（0 结果），PubMed 的 `match_institution` 因子串匹配产生假阳性（"MIT" 误匹配 "Smith"/"Mittone"），`author_affiliations` 在所有源中均为 None。
- **删除范围**：
  1. `name_utils.py` — 删除 `match_institution()` 函数。
  2. `filters.py` — 删除 `institution_bonus` 参数、`_target_institution` 字段、`prepare()` 的 `institution` 参数、评分中的机构加分逻辑。
  3. `harvester.py` — 删除 `_filter_by_institution()` 方法；`search_only()`/`search_only_stream()`/`_search_one_source()` 删除 `institution` 参数及调用。
  4. `pubmed_client.py` / `openalex_client.py` — 删除 `search()` 的 `institution` 参数和相关查询构建逻辑；简化作者解析为仅捕获姓名。
  5. `pipeline_service.py` — 删除 `search_papers_service()`/`search_papers_stream_service()` 的 `institution` 参数。
  6. `main.py` — 删除 `GET /institutions` 端点；删除 `SearchRequest.institution` 字段；更新搜索端点的参数校验。
  7. `author_utils.py` — 简化为 `list[str]` 格式，删除所有 institution 相关处理。
  8. `repositories.py` — 简化 `authors_json` 构建。
  9. `frontend/src/` — 删除 `SearchPage.tsx` 机构筛选 UI（输入框、下拉框、状态）；删除 `api.ts` 中 `getInstitutions` 和 `institution` 类型。
  10. `docs/specs/2026-07-22-author-institution-search.md` — 删除。
- **重建**：前端 `npm run build` 已重新构建。

调试(app/harvest/literature, scripts, app/config): 全量数据源稳定性验证与修复

- **问题**：Semantic Scholar 免费 API（无 key）频繁返回 429 速率限制，`_request_search_page()` 中 `attempt -= 1` 导致无限重试循环（实测 44s+ 仍不休止）。
- **修复**：
  1. 429 重试改为指数退避（2s→4s→8s→16s→32s）+ 累计上限 45s 后快速失败，给出明确错误提示含 API key 注册链接。
  2. `AppConfig` 新增 `semantic_scholar_api_key` / `pubmed_api_key` 字段，从 `.env` 的 `SEMANTIC_SCHOLAR_API_KEY` / `PUBMED_API_KEY` 读取。
  3. `LiteratureHarvester.__init__()` 注入 API key 到 `SemanticScholarClient` 和 `PubmedClient`。
  4. `.env` / `.env.example` 新增 `SEMANTIC_SCHOLAR_API_KEY` / `PUBMED_API_KEY` 配置项（含注册链接说明）。
- **验证**：新建 `scripts/11_test_sources.py` 全量稳定性测试脚本——逐一测试 8 个数据源的连通性、响应时间和结果质量。测试结果：
  - ✅ Europe PMC (2.3s) / arXiv (1.0s) / PubMed (2.4s) / OpenAlex (3.9s) / Nature (2.6s) / Science (2.2s) / Cell (2.4s) — 全部正常。
  - ❌ Semantic Scholar — 免费 tier 429 限流，31s 后快速失败（含修复提示）。

### 2026-07-23

代码生成(app/agent/name_utils, app/harvest/harvester, app/domain/filters): 作者/机构本地精确匹配与评分加分

- **问题**：按作者搜索时，作者筛选完全委托给外部 API（`AUTH:"name"` 语法），中文名依赖 `pypinyin` 转拼音后构建 OR 查询。但 PubMed、OpenAlex 未使用 `name_utils` 转换，Nature/Science/Cell 不支持 author 参数，导致中文作者名匹配失败。
- **修复思路**：改为「API 层粗筛 + 本地精确比对」双层架构：
  1. `name_utils.py` 新增 `match_author()`（支持中文→拼音、首字母缩写匹配、双向包含）和 `match_institution()`（大小写不敏感包含匹配）。
  2. `_search_one_source()` 新增 query 回退：当 query 为空但 author 不为空时，用 `build_author_keyword_query()` 将作者拼音变体作为关键词检索词，确保所有 API 都能返回候选论文。
  3. `harvester.py` 新增 `_filter_by_author()` / `_filter_by_institution()`：在去重后做本地精确过滤。
  4. `QueryDrivenScorer.prepare()` 新增 `author`/`institution` 参数；`score_papers_batch()` 和 `score_paper()` 对匹配作者/机构的论文分别加 0.15/0.10 的 domain_score 加分。
- **依赖修复**：确认 `pypinyin` 已在 scholarflow 环境中安装（requirements.txt 已声明但此前未生效）。

调试(app/harvest, frontend): 前端按钮与实际效果不符——系统性 debug 与修复

- **P0 Bug#7**：`search_only_stream()` SSE 结果 dict 缺少 `tags` 字段，前端流式检索时论文标签（综述/经典）永不渲染。修复：SSE result dict 补全 `"tags": h.tags`。
- **P0 Bug#8**：`_batch_check_in_library()` 不返回 paper.status，前端无法区分「仅元数据」和「已索引」。修复：查询增加 `Paper.status` 字段；`SearchHit` 新增 `library_status`；前端 `PaperCard` 状态显示细化为"已索引/已切块/已解析/已下载PDF/已入库"。
- **P1 Bug#1**：搜索结果「入库」按钮在 importPaper 成功但 processPaper 失败时，状态回滚导致 UI 显示"未入库"而实际已入库。修复：`setImportedIds` 和 `setResult` 提前到 importPaper 成功后执行；processPaper 失败仅警告不改变入库状态。
- **P1 Bug#9**：缺少批量入库/处理 API。新增 `POST /papers/import-batch`（批量 metadata 入库）和 `POST /papers/process-batch`（批量触发流水线），前端 `api.ts` 同步新增 `importPapersBatch()` / `processPapersBatch()`。
- **P2 Bug#2**：「处理」按钮每篇论文独立创建 `setInterval` 轮询 + 30s 硬超时，多篇并发时多定时器竞争。修复：改为全局单一 `useRef` 轮询，检查 `processingIds` 中所有论文状态，全部 `done/failed` 或 60 轮（2分钟）后自动停止。
- **P2 Bug#10**：`_run_pipeline_for_paper()` 每步调用 `list_*_candidates(limit=200)` 再做 O(n) 扫描，批量时 O(n²)。修复：改为直接按 `paper_id` 查询 `PaperRepository.get_paper()` 并检查字段状态，消除候选列表扫描。
- **P3 Bug#3**：前后端双重排序冗余。修复：前端 `handleSearch` 不再传 `sort_by`/`sort_order` 给后端，仅依赖客户端 `useMemo` 排序。
- **P3 Bug#5**：`/papers` 返回 `count` 但前端类型期望 `total`。修复：后端统一改为 `"total"`。
- **P3 Bug#6**：「新建对话」无视觉反馈。修复：点击后显示占位欢迎消息 `"👋 新对话已就绪..."`，同时清除 localStorage 中的旧 session ID。

重构(start.bat, .env.example): 安全性加固与跨机器移植适配

- **安全问题**：`.env` 含真实 `CLOUD_API_KEY`，即使已加入 `.gitignore`，通过 U盘/压缩包分享时仍会泄露。修复：新建 `.env.example` 模板文件，密钥字段替换为占位符 `YOUR_API_KEY`。
- **启动顺序 bug**：`start.bat` 在原逻辑中先检查 Ollama 再加载 `.env`，导致 `LLM_BACKEND=deepseek` 时仍会尝试启动 Ollama。修复：`.env` 加载移至最前，Ollama 检查改为 `if "%LLM_BACKEND%"=="ollama"` 条件化。
- **Python 路径自适应**：新增 `venv\Scripts\python.exe` 检测层级（优先级：项目内 venv > conda scholarflow > 系统 python），`start.bat` 可通用于不同机器的不同 Python 安装方式。
- **错误提示改进**：Python 未找到时给出两条具体操作建议（运行 install_deps.bat 或手动 conda activate）；Ollama 未运行时降级为 `[WARN]` 而非阻塞退出，并提示可切换云端 API。

### 2026-07-22

代码生成(app/harvest, app/services, app/main.py, frontend): 新增机构筛选功能

- 新建 `author_utils.py`：向后兼容的 `authors_json` 解析器，支持旧 `list[str]` 和新 `list[{name, institution}]` 格式。
- `PaperMetadata` 新增 `author_affiliations` 字段。
- OpenAlex 客户端：解析 `authorships[].institutions[]` 并支持 `raw_affiliation_string.search` 过滤。
- PubMed 客户端：新增 `[AD]` 机构检索和 affiliation 解析。
- `SearchHit` 新增 `author_affiliations` 字段；`search_only()`/`search_only_stream()`/`_search_one_source()` 全链路透传 `institution` 参数。
- `main.py`：`SearchRequest` 新增 `institution` 字段；新增 `GET /institutions` 端点（从本地库聚合机构排名，按出现频率降序）。
- 前端 `SearchPage.tsx`：新增机构输入框（combobox 模式，支持自由输入 + 预设下拉列表）；`api.ts` 新增 `getInstitutions()`。

调试(harvester): 修复纯作者/机构搜索时 scorer.prepare() 收到空 query 导致 ValueError

调试(openalex, harvester): 修复 institution 参数无条件透传给不支持的源导致 TypeError；OpenAlex 机构过滤改为搜索词追加（原 raw_affiliation_string.search filter 无效）

代码生成(app/harvest, app/services, app/main.py, frontend): 新增文献语言筛选功能。支持中文/外文/中外文三种模式。Europe PMC 使用 LANG:chi/eng，PubMed 使用 chinese[LA]/english[LA]，OpenAlex 使用 language:zh/en filter。前端新增语言切换按钮组

代码生成(app/harvest, app/main.py, frontend): 新增检索篇数"每源/总计"双模式。每源模式预设 5/10/20/50/100 篇；总计模式跨源汇总后截断至指定篇数。默认改为 10 篇/源

调试(start.bat): 修复 conda Python 路径检测缺陷，解决双击 start.bat 无法唤起后端

- 根因：`for /f "tokens=*"` 将 `conda info --envs` 输出的整行（含大量空格）当作一个字符串，导致 `if exist "%%j\python.exe"` 检查的路径无效。
- 修复：内层循环从 `tokens=*` 改为 `tokens=1*`，按空格拆分列：`%%i`=环境名, `%%j`=路径（同时移除了多余的内层嵌套循环）。
- 验证：`tokens=1*` 正确提取 `C:\Users\HP\.conda\envs\scholarflow`，`python.exe` 存在性检查通过。

文档生成(README): 根据当前项目状态全面更新 README.md

- 数据源数量从 6 更新为 8（新增 PubMed、OpenAlex）。
- LLM 后端从"二选一"更新为"四选一"（新增 OpenAI、Qwen 百炼）。
- API 接口表重新分组为「核心接口/文献库管理/Agent 对话/管理工具/处理流水线」，补充 `/papers/upload-pdf`、`/admin/clear-sessions`、`/admin/clear-all`、`/pipeline/*` 等端点。
- 技术架构图新增 web_search/import_paper 工具、配置管理层、PubMed/OpenAlex 数据源。
- 技术栈表新增「文献源」行，列出全部 8 个数据源。
- 项目结构树展开 `literature/` 下 8 个客户端文件，新增 `config.py`、`llm_factory.py`、`embedding/` 目录。
- 数据目录新增 `pdfs/`、`compounds/`、`spectra/`、`db/` 预留目录。
- Embedding 预热时间从 0.6s 修正为 ~6s（后台线程预热）。
- 常见问题更新 LLM 切换选项和检索耗时估算。

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

文档生成(教程): 更新 ScholarFlow使用教程.docx 至最新项目状态

- 修正 Python 版本：3.12+ → 3.10~3.12。
- 准备工作从"三个软件"改为"四项准备"：新增 [4] BGE-M3 嵌入模型下载步骤（含完整 python 命令和国内镜像提示）。
- 删除"同时打开两次浏览器"说明（该 bug 已修复）。
- 启动说明加上"确保四项准备都已就绪"的前提。
- 常见问题新增 BGE-M3 模型下载相关问答。
- 目录结构新增 `embedding/bge-m3/` 条目。

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

### 2026-07-21

代码生成(配置管理): Phase 1 基础设施 —— AppConfig 单例 + LLMFactory 统一创建

- 三轮自审分析定位 11 个 bug，核心问题为 LLM 配置碎片化：`LLM_BACKEND` 仅 `agent.py` 一处生效，其余 5 个模块硬编码 Ollama。
- 新建 `app/config.py`：`AppConfig` 类（纯 Python，零新依赖），从 `.env` 加载全部配置，`get_config()` 线程安全单例。覆盖数据库/LLM/Embedding/生成参数 15+ 字段。
- 新建 `app/llm_factory.py`：`RawLLMClient` 抽象接口 + `OllamaRawClient`/`OpenAIRawClient` 实现（同步+异步），统一 Ollama `/api/chat` 和 OpenAI `/chat/completions`。`create_chat_model()` 返回 LangChain ChatModel，`create_raw_llm()` 返回底层 HTTP 客户端。
- 设计文档：`docs/specs/configuration-management.md`（5 阶段实施计划）+ `docs/specs/bug-fix-plan.md`（11 个 bug 逐一方案）。

修复(database): BUG-7 数据库默认地址 localhost → 127.0.0.1

- `database.py`：`DATABASE_URL` 默认值从 `@localhost:5433` 改为 `@127.0.0.1:5433`，避免 WSL2 下 IPv6 解析延迟 5s。

修复(frontend): BUG-5 翻译竞态条件 + BUG-9 类型安全

- `SearchPage.tsx`：`handleCardClick` 新增 `translateRequestIdRef`（useRef 计数器），then/catch/finally 中校验 requestId，消除快速切换卡片的竞态条件。
- `SearchPage.tsx`：新增 `translationError` 状态，API 失败时 UI 展示红色"翻译失败，请稍后重试"，区分"无需翻译"和"翻译失败"。
- `SearchPage.tsx`：关闭模态框时同步重置 `translationError` 和 `translating`。
- `SearchPage.tsx`：`importingIds`/`importedIds` 类型从 `Set<number>` 改为 `Set<string>`，key 改用 `hit.doi || hit.title`，消除 `as unknown as number` 类型绕过。

修复(backend): BUG-4 翻译 max_tokens 2048 → 4096

- `main.py`：`/translate` 端点 deepseek 路径 `max_tokens: 2048→4096`，ollama 路径 `num_predict: 2048→4096`，防止长摘要翻译截断。

修复(startup): BUG-6 HF_HUB_OFFLINE 覆盖 + BUG-11 Python 路径硬编码

- `.env`：`HF_HUB_OFFLINE=0→1`，启用离线模式避免 BGE-M3 加载时 10+ HF Hub 网络请求。
- `start.bat`：`.env` 加载改为 `if not defined` 保护已设变量不被覆盖；Python 路径从硬编码 `C:\Users\HP\...` 改为自动检测 conda scholarflow 环境 → 兜底当前 `python`。

修复(frontend+backend): 摘要翻译三项修复 —— 竞态条件 + 错误处理误导 + max_tokens 截断

- 三轮自审分析定位三个 bug：(1) 快速切换卡片时旧请求覆盖新结果（竞态条件）；(2) API 失败时 catch 设 null 导致 UI 显示"已为中文，无需翻译"误导用户；(3) max_tokens=2048 可能截断长摘要。
- `SearchPage.tsx`：`handleCardClick` 新增 `translateRequestIdRef`（useRef 计数器），每次点击递增 requestId，then/catch/finally 中校验 requestId 是否匹配当前卡片，消除竞态条件。
- `SearchPage.tsx`：新增 `translationError` 状态，API 失败时设为 true，UI 展示"翻译失败，请稍后重试"（红色），区分"无需翻译"和"翻译失败"。
- `SearchPage.tsx`：关闭模态框时同步重置 `translationError` 状态。
- `main.py`：`/translate` 端点 max_tokens / num_predict 从 2048 提升至 4096，防止长摘要翻译截断。

代码生成(frontend+backend): 三级缓存清除功能 —— 侧边栏「工具」下拉菜单 + 二次确认对话框

- 设计方案：侧边栏底部新增「⚙ 工具」下拉菜单，三个清除等级，最高等级需输入「确认删除」二次确认。
- `repositories.py`：`PaperRepository` 新增 `get_all_paper_ids()`（返回 ID+文件路径）和 `delete_all_papers()`（批量删除+级联 chunks）。
- `main.py`：新增 `POST /admin/clear-sessions`（调用 `SessionManager.clear_all()`）和 `POST /admin/clear-all`（删除 DB 记录→PDF→文本→FAISS 索引→会话，返回统计信息）。
- `api.ts`：新增 `clearSessions()` 和 `clearAll()` 两个 API 方法。
- 新建 `ClearAllDialog.tsx`：模态框二次确认组件，输入「确认删除」匹配后才允许点击确认按钮，支持 loading 状态。
- `Sidebar.tsx`：新增「工具」按钮（Wrench 图标），点击弹出三选项下拉菜单；第一级「清除前端缓存」清除两个 localStorage key；第二级「清除前端+历史」额外调 `/admin/clear-sessions`；第三级「清除所有数据」弹出 ClearAllDialog 确认后调 `/admin/clear-all`；成功提示 2.5 秒自动消失。

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

### 2026-07-14

代码生成(harvester/clients): Europe PMC / arXiv / Semantic Scholar 客户端新增 author 参数，支持按作者名过滤检索

- `europe_pmc_client.py`: `search()` 新增 `author` 参数，查询时拼入 `AUTH:"name"` 语法。
- `arxiv_client.py`: `search()` + `_request_search_page()` 新增 `author` 参数，查询时拼入 `au:"name"` 前缀。
- `semantic_scholar_client.py`: `search()` 新增 `author` 参数，查询时嵌入作者名精确匹配。
- `harvester.py`: `_search_one_source()` / `search_only()` / `search_only_stream()` 全链路新增 `author` 参数透传。
- `pipeline_service.py`: `search_papers_service()` / `search_papers_stream_service()` 新增 `author` 参数透传。

代码生成(agent): 新增 web_search 工具模块（DuckDuckGo），Agent 可并行调用文献 API + 网页搜索查找作者论文

- 新建 `app/agent/web_search.py`，封装 DuckDuckGo 免费网页搜索（`duckduckgo_search>=7.0.0`）。
- `tools.py` 新增 `@tool web_search(query, max_results)` 工具，返回标题/摘要/URL 列表。
- `ALL_TOOLS` 加入 `web_search`。
- `search_papers` 工具新增 `author` 参数，调用时透传至 pipeline_service。

代码生成(agent): 更新 Agent 系统提示词，编排 author search + web_search 双通道作者论文查询

- `agent.py` 系统提示词新增规则：用户查询作者论文时，先调用 `search_papers(author=...)` 从学术数据库检索，同时/随后调用 `web_search` 补充网页来源。

代码生成(api): SearchRequest 模型新增 author 字段，/search 和 /search/stream 端点透传作者参数

- `main.py`: `SearchRequest` 新增 `author: Optional[str]` 字段。
- `POST /search` 和 `POST /search/stream` 端点传递 `author` 到 service 层。
- 四个 `requirements/*.txt` 文件均追加 `duckduckgo_search>=7.0.0` 依赖。

代码生成(frontend): SearchPage 新增作者输入框，支持按作者名筛选检索结果

- `api.ts`: `search()` 方法新增 `author?: string` 参数。
- `SearchPage.tsx`: 新增 `author` 状态、localStorage 持久化、作者输入框 UI（含清除按钮），搜索时透传 `author` 参数。

代码生成(agent/name_utils): 中文作者名自动扩展为 8 种英文拼音变体 OR 查询

- 新建 `app/agent/name_utils.py`，基于 `pypinyin` 将中文名转为拼音，生成 8 种常见英文署名格式变体（名姓/姓名/连写/全小写等）。
- `europe_pmc_client.py` / `arxiv_client.py` / `semantic_scholar_client.py` 三个客户端在 `author` 含中文时自动调用 `build_author_or_query()` / `expand_chinese_name()` 构建 OR 查询。
- 四个 `requirements/*.txt` 文件均追加 `pypinyin>=0.55.0` 依赖。

代码生成(harvester+api+frontend): 支持纯作者检索 — 无需主题关键词，直接输入作者名即可查论文

- `harvester.py` `search_only` / `search_only_stream`: query 校验从必填改为"query 和 author 至少提供一个"。
- 三个客户端 `europe_pmc_client.py` / `arxiv_client.py` / `semantic_scholar_client.py`: 同上校验放宽；当 query 为空时，author 查询片段独立构成检索表达式（不含多余前缀）。
- `main.py` `/search` 和 `/search/stream`: 允许 query 为空当 author 提供时，错误提示更新。
- `SearchPage.tsx`: 关键词输入框改为可选；搜索按钮在仅填写作者名时也可点击。

性能优化(embedder+main): 启动速度从 9-14s 降至 <1s — warmup 后台化 + 跳过首次 encode + 强制 CUDA

- `embedder.py`: `_infer_dimension()` 新增 `_KNOWN_DIMENSIONS` 硬编码表（bge-m3→1024），已知模型跳过首次 encode 省 2-3s。
- `main.py` lifespan: BGE-M3 warmup 从同步阻塞改为 `threading.Thread(daemon=True)` 后台加载，服务器立即就绪。
- `main.py` lifespan: 强制 `device='cuda'`（CUDA 可用时），模型加载从 11s（CPU）降至 7s（GPU）。
- 效果：用户感知启动时间 0.6s，模型在后台 6.9s 热好。

代码生成(agent): Agent 回复格式规范化 + 搜索深度 + import_paper 入库工具

- `tools.py`: `search_papers` 输出新增 `authors` 字段；新增 `import_paper` 工具（title/authors/doi/year/journal→入库）。
- `agent.py` 系统提示词全面升级：论文结果必须用 Markdown 表格展示 metadata（不能只回作者名）；缺失字段留空不编造；搜索后主动提供入库选项。
- `agent.py` `run_agent()` 新增 `search_depth` 参数：quick=仅标题年份，deep（默认）=完整 metadata + 入库建议。以前置指令注入到用户消息中。
- `main.py`: `AgentChatRequest` 新增 `search_depth` 字段（quick/deep），透传到 `run_agent()`。

### 2026-07-21

代码生成(harvester+api+frontend): 期刊筛选第二层 — Nature/Science/Cell 假源退役，替换为期刊下拉

- `europe_pmc_client.py`: `search()` 新增 `journal` 参数，支持 `JOURNAL:"Name"` 语法。
- `harvester.py`: `_search_one_source` / `search_only` / `search_only_stream` 全链路新增 `journal` 参数透传。
- `pipeline_service.py`: `search_papers_service` / `search_papers_stream_service` 新增 `journal` 参数。
- `main.py`: `SearchRequest` 新增 `journal` 字段，`/search` 和 `/search/stream` 端点透传。
- `SearchPage.tsx`: SOURCES 从 6→3（移除 nature/science/cell 假源）；新增 17 个预设期刊下拉 + 自定义输入；`journal` 状态持久化到 localStorage。
- `api.ts`: `search` / `searchStream` 参数新增 `journal`。

### 2026-07-21 (Phase 2)

代码生成(harvest/clients): 新增 PubMed 和 OpenAlex 文献客户端

- 新建 `app/harvest/literature/pubmed_client.py`：NCBI E-utilities API（esearch + esummary），返回 MeSH pubtype 列表，免费 3 req/s（可注册 key 提至 10/s）。
- 新建 `app/harvest/literature/openalex_client.py`：OpenAlex REST API（250M+ 作品），返回引用计数、摘要重建、开放获取信息。
- `harvester.py`：`_get_search_fn` 新增 `pubmed` / `openalex` 源映射；`LiteratureHarvester.__init__` 实例化两个新客户端。

代码生成(domain): 质量评分增强 — 多因子加权

- `filters.py` 新增 `compute_quality_score(domain_score, citation_count, year, source)`：四因子加权（语义 0.40 / 引用 0.25 / 时效 0.20 / 来源信誉 0.15）。
- arXiv 特殊处理：引用权重翻倍至 0.50，无时效衰减。

代码生成(frontend): SOURCES 数据源新增 PubMed 和 OpenAlex
### 2026-07-22 (Phase 4)

代码生成(brand): ScholarFlow → ScholarFlow-Bio 品牌升级 + DNA Logo

- 新建 `frontend/src/components/Logo.tsx`：SVG DNA 双螺旋 + "ScholarFlow" + "-Bio" 下标（indigo/emerald 配色）。
- `Sidebar.tsx`：Logo 替换旧的方框+书图标；副标题改为"生物医学文献智能体"。
- `index.html`：`<title>` 改为 "ScholarFlow-Bio — 生物医学文献智能体"。
- `main.py`：FastAPI title/description 升级为 ScholarFlow-Bio，version 1.3.0。
- `package.json`：name 改为 `scholarflow-bio-frontend`。
- `README.md`：标题/描述更新为 ScholarFlow-Bio。
- `SearchPage.tsx`：SOURCES 从 3→5（+PubMed、+OpenAlex）。

