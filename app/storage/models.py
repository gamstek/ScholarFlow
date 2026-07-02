"""
models.py

SQLAlchemy ORM 模型定义（PostgreSQL）。

从 dataclass 迁移到 DeclarativeBase，保持与原 SQLite schema 一致。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """SQLAlchemy 基类。"""
    pass


class CrawlTask(Base):
    """采集任务表。"""

    __tablename__ = "crawl_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(Text, nullable=False)
    task_type = Column(String(50), nullable=False, default="literature")
    sources_json = Column(Text, nullable=True)
    max_results = Column(Integer, default=20)
    status = Column(String(20), nullable=False, default="pending")
    success_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    agent_state = Column(Text, nullable=True)  # JSON: 当前阶段、子任务列表、错误信息
    parent_task_id = Column(Integer, nullable=True)  # 子任务父级 task_id
    created_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)

    papers = relationship("Paper", back_populates="crawl_task")


class ResearchProtocol(Base):
    """研究协议表 — C01 研究问题建模与项目协议。

    将自然语言课题分解为结构化 PICO 框架 + 纳排标准。
    协议是后续检索、筛选、综合和更新的共同约束。
    """

    __tablename__ = "research_protocols"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 关联项目
    project_name = Column(String(200), nullable=False, default="默认项目")

    # 用户原始输入
    raw_question = Column(Text, nullable=False)

    # PICO 框架（JSON）
    pico_json = Column(Text, nullable=True)
    # {"population": "...", "intervention": "...", "comparison": "...", "outcome": "..."}

    # 检索协议
    keywords_en = Column(Text, nullable=True)   # 英文关键词，换行分隔
    keywords_zh = Column(Text, nullable=True)   # 中文关键词，换行分隔
    search_query = Column(Text, nullable=True)  # 推荐的布尔检索式

    # 纳入/排除标准（JSON 数组）
    inclusion_criteria = Column(Text, nullable=True)  # JSON: [{criterion, rationale}]
    exclusion_criteria = Column(Text, nullable=True)  # JSON: [{criterion, rationale}]

    # 文献范围
    time_from = Column(Integer, nullable=True)
    time_to = Column(Integer, nullable=True)
    languages = Column(String(200), nullable=True)       # 逗号分隔
    study_types = Column(Text, nullable=True)             # JSON 数组
    data_sources = Column(Text, nullable=True)            # JSON 数组

    # 状态与控制
    status = Column(String(20), nullable=False, default="draft", index=True)
    # draft → pending_approval → approved → archived
    version = Column(Integer, nullable=False, default=1)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(100), nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Paper(Base):
    """文献表。"""

    __tablename__ = "papers"
    __table_args__ = (
        UniqueConstraint("doi", name="uq_papers_doi"),
        UniqueConstraint("pmid", name="uq_papers_pmid"),
        UniqueConstraint("pmcid", name="uq_papers_pmcid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False, index=True)
    abstract = Column(Text, nullable=True)
    authors_json = Column(Text, nullable=True)
    year = Column(Integer, nullable=True, index=True)
    journal = Column(String(500), nullable=True)
    doi = Column(String(500), nullable=True)
    pmid = Column(String(100), nullable=True)
    pmcid = Column(String(100), nullable=True)
    crossref_id = Column(String(200), nullable=True)
    source = Column(String(100), nullable=True)
    url = Column(Text, nullable=True)
    pdf_url = Column(Text, nullable=True)
    local_pdf_path = Column(Text, nullable=True)
    local_text_path = Column(Text, nullable=True)
    license = Column(String(500), nullable=True)
    is_open_access = Column(Integer, nullable=False, default=0)
    domain_score = Column(Float, default=0.0, index=True)
    status = Column(String(30), nullable=False, default="metadata_only")
    crawl_task_id = Column(Integer, ForeignKey("crawl_tasks.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    crawl_task = relationship("CrawlTask", back_populates="papers")
    chunks = relationship("Chunk", back_populates="paper", cascade="all, delete-orphan")


class Chunk(Base):
    """文本片段表。"""

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("paper_id", "chunk_index", name="uq_chunks_paper_chunk"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    section_title = Column(Text, nullable=True, index=True)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    text = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=True)
    embedding_status = Column(String(20), nullable=False, default="pending", index=True)
    faiss_vector_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    paper = relationship("Paper", back_populates="chunks")


class Compound(Base):
    """化合物表（空表骨架）。"""

    __tablename__ = "compounds"

    id = Column(Integer, primary_key=True, autoincrement=True)


class Spectrum(Base):
    """谱图表（空表骨架）。"""

    __tablename__ = "spectra"

    id = Column(Integer, primary_key=True, autoincrement=True)


class PaperCompoundLink(Base):
    """文献-化合物关联表。"""

    __tablename__ = "paper_compound_links"
    __table_args__ = (
        UniqueConstraint("paper_id", "compound_id", "mention_text", name="uq_paper_compound_link"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    compound_id = Column(Integer, ForeignKey("compounds.id", ondelete="CASCADE"), nullable=False, index=True)
    mention_text = Column(Text, nullable=True)
    section = Column(String(200), nullable=True)
    confidence = Column(Float, default=0.0)
    created_at = Column(DateTime, server_default=func.now())
