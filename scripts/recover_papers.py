"""
从 data/texts/ 和 data/papers/ 恢复论文到 PostgreSQL 数据库。

用法：
    cd d:\ScholarFlow
    python scripts\recover_papers.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# 确保项目根目录在 Python path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text as sa_text
from app.storage.database import async_session_factory, async_engine, PROJECT_ROOT, TEXTS_DIR

TEXTS_DIR_PATH = PROJECT_ROOT / "data" / "texts"
PAPERS_DIR_PATH = PROJECT_ROOT / "data" / "papers"
PDFS_DIR_PATH = PROJECT_ROOT / "data" / "pdfs"


async def recover():
    text_files = sorted(TEXTS_DIR_PATH.glob("paper_*.json"))
    print(f"找到 {len(text_files)} 个文本文件")

    success = 0
    skipped = 0
    failed = 0

    for tf in text_files:
        try:
            with open(tf, "r", encoding="utf-8") as f:
                data = json.load(f)

            paper_meta = data.get("paper", {})
            pdf_info = data.get("pdf", {})
            pages = data.get("pages", [])

            title = paper_meta.get("title", "")
            if not title:
                print(f"  跳过（无标题）: {tf.name}")
                skipped += 1
                continue

            doi = paper_meta.get("doi") or None
            pmid = paper_meta.get("pmid") or None
            pmcid = paper_meta.get("pmcid") or None
            year = paper_meta.get("year") or None
            journal = paper_meta.get("journal") or None
            source = paper_meta.get("source", "europe_pmc")
            url = paper_meta.get("url") or None
            pdf_url = paper_meta.get("pdf_url") or None
            # Try to determine is_open_access
            is_open_access = 0
            if pdf_url and ("europepmc.org/articles" in pdf_url or "pmc" in pdf_url.lower()):
                is_open_access = 1

            # Determine PDF path
            old_pdf_path = pdf_info.get("local_pdf_path", "")
            # Old path format: "data\\papers\\paper_X_....pdf"
            # New format: "data/papers/paper_X_....pdf" or "data/pdfs/paper_X.pdf"
            pdf_filename = Path(old_pdf_path).name if old_pdf_path else None

            local_pdf_path = None
            if pdf_filename:
                # Check in both locations
                candidates = [
                    PAPERS_DIR_PATH / pdf_filename,
                    PDFS_DIR_PATH / pdf_filename,
                ]
                for cand in candidates:
                    if cand.exists():
                        # Use relative path with forward slashes
                        local_pdf_path = str(cand.relative_to(PROJECT_ROOT)).replace("\\", "/")
                        break

            # Step 1: Insert paper metadata into DB
            async with async_session_factory() as session:
                if doi:
                    # Upsert by DOI (ON CONFLICT only works with non-null unique)
                    result = await session.execute(
                        sa_text(
                            """INSERT INTO papers (title, abstract, authors_json, year, journal, doi, pmid, pmcid,
                               source, url, pdf_url, license, is_open_access, domain_score, status,
                               local_pdf_path, pipeline_step)
                               VALUES (:title, :abstract, :authors_json, :year, :journal, :doi, :pmid, :pmcid,
                               :source, :url, :pdf_url, :license, :is_open_access, :domain_score, :status,
                               :local_pdf_path, :pipeline_step)
                               ON CONFLICT (doi) DO UPDATE SET
                               title = EXCLUDED.title,
                               year = EXCLUDED.year,
                               local_pdf_path = EXCLUDED.local_pdf_path,
                               status = EXCLUDED.status,
                               pipeline_step = EXCLUDED.pipeline_step
                               RETURNING id"""
                        ),
                        {
                            "title": title,
                            "abstract": None,
                            "authors_json": None,
                            "year": year,
                            "journal": journal,
                            "doi": doi,
                            "pmid": pmid,
                            "pmcid": pmcid,
                            "source": source,
                            "url": url,
                            "pdf_url": pdf_url,
                            "license": None,
                            "is_open_access": is_open_access,
                            "domain_score": 0.0,
                            "status": "parsed",
                            "local_pdf_path": local_pdf_path,
                            "pipeline_step": "done",
                        },
                    )
                    row = result.fetchone()
                    paper_id = row[0] if row else None
                    if not paper_id:
                        result2 = await session.execute(
                            sa_text("SELECT id FROM papers WHERE doi = :doi"),
                            {"doi": doi},
                        )
                        paper_id = result2.fetchone()[0]
                else:
                    # No DOI: plain insert (should not duplicate)
                    result = await session.execute(
                        sa_text(
                            """INSERT INTO papers (title, abstract, authors_json, year, journal, doi, pmid, pmcid,
                               source, url, pdf_url, license, is_open_access, domain_score, status,
                               local_pdf_path, pipeline_step)
                               VALUES (:title, :abstract, :authors, :year, :journal, :doi, :pmid, :pmcid,
                               :source, :url, :pdf_url, :license, :is_open_access, :domain_score, :status,
                               :local_pdf_path, :pipeline_step)
                               RETURNING id"""
                        ),
                        {
                            "title": title,
                            "abstract": None,
                            "authors": None,
                            "year": year,
                            "journal": journal,
                            "doi": doi,
                            "pmid": pmid,
                            "pmcid": pmcid,
                            "source": source,
                            "url": url,
                            "pdf_url": pdf_url,
                            "license": None,
                            "is_open_access": is_open_access,
                            "domain_score": 0.0,
                            "status": "parsed",
                            "local_pdf_path": local_pdf_path,
                            "pipeline_step": "done",
                        },
                    )
                    paper_id = result.fetchone()[0]

                await session.commit()

            # Step 2: Save reconstructed full text as local_text_path
            if pages:
                full_text_lines = []
                for page in sorted(pages, key=lambda p: p.get("page_number", 0)):
                    full_text_lines.append(page.get("text", ""))
                full_text = "\n\n".join(full_text_lines)

                text_filename = tf.stem + ".txt"
                text_rel_path = f"data/texts/{text_filename}"
                text_abs_path = PROJECT_ROOT / text_rel_path
                text_abs_path.write_text(full_text, encoding="utf-8")

                async with async_session_factory() as session:
                    await session.execute(
                        sa_text(
                            "UPDATE papers SET local_text_path = :path, status = 'parsed' WHERE id = :id"
                        ),
                        {"path": text_rel_path, "id": paper_id},
                    )
                    await session.commit()

            print(f"  [OK] paper_id={paper_id}: {title[:60]}...")
            success += 1

        except Exception as exc:
            print(f"  [FAIL] {tf.name}: {exc}")
            failed += 1

    print(f"\n恢复完成: 成功 {success}, 跳过 {skipped}, 失败 {failed}")


if __name__ == "__main__":
    asyncio.run(recover())
