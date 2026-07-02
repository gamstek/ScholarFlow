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
