"""
修复 local_text_path — 指向原始 JSON 文件（chunker 需要 JSON 格式）。

用法：
    cd d:\ScholarFlow
    python scripts\fix_text_paths.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text as sa_text
from app.storage.database import async_session_factory


async def fix():
    project_root = Path(__file__).resolve().parents[1]
    texts_dir = project_root / "data" / "texts"

    async with async_session_factory() as session:
        # 查询所有 parsed 状态的论文
        result = await session.execute(
            sa_text(
                "SELECT id, local_text_path FROM papers WHERE status = 'parsed' AND local_text_path IS NOT NULL"
            )
        )
        rows = result.fetchall()

    fixed = 0
    for row in rows:
        paper_id, current_path = row[0], row[1]
        if not current_path:
            continue

        # 从 .txt 路径推导对应的 .json 文件
        # 例如: data/texts/paper_1_...txt -> paper_1_....json
        txt_name = Path(current_path).stem  # "paper_1_..."
        json_name = txt_name + ".json"
        json_full = texts_dir / json_name
        relative_json = f"data/texts/{json_name}"

        if json_full.exists():
            async with async_session_factory() as session:
                await session.execute(
                    sa_text(
                        "UPDATE papers SET local_text_path = :path, status = 'parsed' WHERE id = :id"
                    ),
                    {"path": relative_json, "id": paper_id},
                )
                await session.commit()
            print(f"  [OK] paper_id={paper_id}: {relative_json}")
            fixed += 1
        else:
            print(f"  [MISS] paper_id={paper_id}: JSON 文件不存在: {relative_json}")

    print(f"\n修复完成: {fixed} 篇")


if __name__ == "__main__":
    asyncio.run(fix())
