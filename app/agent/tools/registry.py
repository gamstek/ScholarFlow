"""
registry.py

全局 ToolRegistry 实例。

所有 Tool 在此注册后，Agent 可以通过名称查找并调用。

注册的 Tool 一览：
- search_literature       (采集类) 从 Europe PMC 检索文献
- fetch_paper_metadata    (采集类) 查询文献元数据
- filter_by_domain         (采集类) 领域相关性评分
- crossref_search          (采集类) Crossref 检索（骨架）
- download_open_access_pdf (处理类) 下载 OA PDF
- parse_pdf                (处理类) 解析 PDF 提取文本
- build_chunks             (处理类) 构建 chunks
- build_faiss_index        (处理类) 向量化写入 FAISS
- rag_search               (检索类) 本地 FAISS 检索
- rag_ask                  (检索类) RAG 问答
- check_paper_status       (检索类) 查看文献状态
- list_papers              (辅助类) 列出文献库
- write_dev_log            (辅助类) 写开发日志
"""

import logging

from app.agent.base import ToolRegistry

logger = logging.getLogger(__name__)

# 全局 Tool 注册中心
tool_registry = ToolRegistry()


def _register_all() -> None:
    """注册所有 Tool。在模块导入时自动执行。"""
    try:
        from app.agent.tools.literature import (
            CrossrefSearchTool,
            FetchPaperMetadataTool,
            FilterByDomainTool,
            SearchLiteratureTool,
        )
        from app.agent.tools.pipeline import (
            BuildChunksTool,
            BuildFaissIndexTool,
            DownloadOpenAccessPdfTool,
            ParsePdfTool,
        )
        from app.agent.tools.rag import (
            CheckPaperStatusTool,
            RagAskTool,
            RagSearchTool,
        )
        from app.agent.tools.utils import ListPapersTool, WriteDevLogTool

        # 采集类
        tool_registry.register(SearchLiteratureTool())
        tool_registry.register(FetchPaperMetadataTool())
        tool_registry.register(FilterByDomainTool())
        tool_registry.register(CrossrefSearchTool())

        # 处理类
        tool_registry.register(DownloadOpenAccessPdfTool())
        tool_registry.register(ParsePdfTool())
        tool_registry.register(BuildChunksTool())
        tool_registry.register(BuildFaissIndexTool())

        # 检索类
        tool_registry.register(RagSearchTool())
        tool_registry.register(RagAskTool())
        tool_registry.register(CheckPaperStatusTool())

        # 辅助类
        tool_registry.register(ListPapersTool())
        tool_registry.register(WriteDevLogTool())

        logger.info("ToolRegistry 初始化完成，已注册 %d 个 Tool。", len(tool_registry))
    except Exception as exc:
        logger.warning("ToolRegistry 初始化部分失败：%s", exc)


_register_all()
