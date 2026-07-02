"""
database.py

数据库基础层 Database Layer（PostgreSQL + SQLAlchemy async）。

作用：
1. 管理数据库连接（asyncpg 驱动）；
2. 创建 data/ 目录结构；
3. 提供异步 SQLAlchemy 引擎与会话工厂；
4. 初始化数据表。

迁移说明：
    从 SQLite (sqlite3) 迁移到 PostgreSQL (asyncpg + SQLAlchemy)，
    支持大规模文献数据和并发读写。
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ============================================================
# 1. 项目路径配置
# ============================================================

CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]

DATA_DIR = PROJECT_ROOT / "data"
DB_DIR = DATA_DIR / "db"
PAPERS_DIR = DATA_DIR / "papers"
TEXTS_DIR = DATA_DIR / "texts"
SPECTRA_DIR = DATA_DIR / "spectra"
COMPOUNDS_DIR = DATA_DIR / "compounds"
INDEX_DIR = DATA_DIR / "index"

# 旧 SQLite 路径（保留兼容）
OLD_DB_PATH = DB_DIR / "food_structure_rag.db"

# ============================================================
# 2. 数据库连接配置
# ============================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:scholarflow@localhost:5432/scholarflow",
)

async_engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=10,
    echo=False,
)

async_session_factory = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def ensure_data_dirs() -> None:
    """创建项目运行所需的数据目录。"""
    for directory in [
        DATA_DIR,
        DB_DIR,
        PAPERS_DIR,
        TEXTS_DIR,
        SPECTRA_DIR,
        COMPOUNDS_DIR,
        INDEX_DIR,
    ]:
        directory.mkdir(parents=True, exist_ok=True)


async def get_db() -> AsyncSession:
    """
    FastAPI 依赖注入：获取异步数据库会话。

    用法：
        @app.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """
    初始化数据库表结构。

    使用 SQLAlchemy create_all 创建所有 ORM 模型对应的表。
    对已有表执行 ADD COLUMN IF NOT EXISTS 以兼容迁移。
    """
    ensure_data_dirs()

    from app.storage.models import Base

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 数据库迁移：已有表新增列（create_all 对已有表不会自动新增列）
    async with async_engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE crawl_tasks ADD COLUMN IF NOT EXISTS agent_state TEXT;"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE crawl_tasks ADD COLUMN IF NOT EXISTS parent_task_id INTEGER;"
            )
        )

    # 验证连接
    async with async_session_factory() as session:
        await session.execute(text("SELECT 1"))


async def close_db() -> None:
    """关闭数据库引擎。"""
    await async_engine.dispose()


def get_connection():
    """
    同步兼容层：为尚未迁移的业务逻辑提供数据库访问。

    ⚠ 仅用于过渡期，待所有调用方迁移至 async 后删除。
    """
    import asyncio
    from sqlalchemy import text as sa_text

    async def _query(sql: str, params=None) -> list[dict]:
        async with async_session_factory() as session:
            result = await session.execute(sa_text(sql), params or {})
            rows = result.fetchall()
            return [dict(row._mapping) for row in rows]

    class SyncCompat:
        """模拟 sqlite3.Connection 最小接口。"""
        def cursor(self):
            return _SyncCursor()
        def commit(self):
            pass
        def close(self):
            pass

    class _SyncCursor:
        """模拟 sqlite3.Cursor 最小接口。"""
        def execute(self, sql: str, params=None):
            self._sql = sql
            self._params = params
            # 将 SQLite ? 占位符转为 SQLAlchemy :pN 格式
            import re
            if params and isinstance(params, (tuple, list)):
                param_dict = {}
                counter = [0]
                def replacer(match):
                    key = f"p{counter[0]}"
                    counter[0] += 1
                    param_dict[key] = params[counter[0] - 1]
                    return f":{key}"
                sql = re.sub(r"\?", replacer, sql)
                params = param_dict
            self._rows = asyncio.run(_query(sql, params))
            return self

        def fetchone(self):
            return RowCompat(self._rows[0]) if self._rows else None

        def fetchall(self):
            return [RowCompat(r) for r in self._rows]

    class RowCompat(dict):
        """模拟 sqlite3.Row，支持 dict 和索引访问。"""
        pass

    return SyncCompat()
