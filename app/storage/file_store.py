"""
file_store.py

本地文件存储模块 File Store。

作用：
1. 管理 PDF 文件保存路径；
2. 管理 PDF 解析后文本 JSON 保存路径；
3. 生成安全文件名；
4. 计算文件哈希；
5. 检查文件是否为 PDF；
6. 将相对路径和绝对路径互相转换。

当前保存目录：
    data/papers/     保存 PDF 原文
    data/texts/      保存 PDF 解析后的结构化文本 JSON
    data/spectra/    保存谱图原始数据
    data/compounds/  保存化合物结构缓存
    data/index/      保存 FAISS 向量索引
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

from app.storage.database import (
    PAPERS_DIR,
    PROJECT_ROOT,
    TEXTS_DIR,
    ensure_data_dirs,
)


def sanitize_filename(value: str, max_length: int = 120) -> str:
    """
    将字符串转换成适合文件名的安全形式。

    参数：
        value:
            原始字符串，比如标题、DOI。

        max_length:
            文件名最大长度，避免 Windows 路径过长。

    返回：
        安全文件名字符串。

    示例：
        "LC-MS/MS analysis: HMO?" -> "LC-MS_MS_analysis_HMO"
    """
    if not value:
        return "untitled"

    value = value.strip()

    # Windows 不允许的文件名字符：<>:"/\\|?*
    value = re.sub(r'[<>:"/\\|?*]+', "_", value)

    # 把连续空白替换成下划线
    value = re.sub(r"\s+", "_", value)

    # 去掉连续下划线
    value = re.sub(r"_+", "_", value)

    # 去掉首尾无意义字符
    value = value.strip("._- ")

    if not value:
        return "untitled"

    return value[:max_length]


def build_pdf_filename(
    paper_id: int,
    title: str,
    doi: Optional[str] = None,
) -> str:
    """
    为某篇文献生成 PDF 文件名。

    命名策略：
        paper_{paper_id}_{doi}_{title}.pdf

    为什么带 paper_id？
        1. 避免同名论文冲突；
        2. 方便根据文件反查数据库；
        3. 后续批量处理时更稳定。
    """
    title_part = sanitize_filename(title, max_length=100)

    if doi:
        doi_part = sanitize_filename(doi, max_length=50)
        return f"paper_{paper_id}_{doi_part}_{title_part}.pdf"

    return f"paper_{paper_id}_{title_part}.pdf"


def build_text_filename(
    paper_id: int,
    title: str,
    doi: Optional[str] = None,
) -> str:
    """
    为某篇文献生成解析文本 JSON 文件名。

    命名策略：
        paper_{paper_id}_{doi}_{title}.json

    注意：
        这里保存的是结构化 JSON，不是普通 txt。
        原因：
            1. 可以保留页码；
            2. 可以保留章节信息；
            3. 后续切 chunk 时更容易追溯来源。
    """
    title_part = sanitize_filename(title, max_length=100)

    if doi:
        doi_part = sanitize_filename(doi, max_length=50)
        return f"paper_{paper_id}_{doi_part}_{title_part}.json"

    return f"paper_{paper_id}_{title_part}.json"


def get_pdf_path(
    paper_id: int,
    title: str,
    doi: Optional[str] = None,
) -> Path:
    """
    获取某篇文献 PDF 应该保存到的路径。
    """
    ensure_data_dirs()

    filename = build_pdf_filename(
        paper_id=paper_id,
        title=title,
        doi=doi,
    )

    return PAPERS_DIR / filename


def get_text_path(
    paper_id: int,
    title: str,
    doi: Optional[str] = None,
) -> Path:
    """
    获取某篇文献解析文本 JSON 应该保存到的路径。
    """
    ensure_data_dirs()

    filename = build_text_filename(
        paper_id=paper_id,
        title=title,
        doi=doi,
    )

    return TEXTS_DIR / filename


def save_json(
    data: dict[str, Any],
    output_path: Path,
) -> None:
    """
    将字典保存为 JSON 文件。

    参数：
        data:
            需要保存的数据。

        output_path:
            输出路径。

    说明：
        ensure_ascii=False 可以保留中文；
        indent=2 方便人工查看。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


def load_json(
    input_path: Path,
) -> dict[str, Any]:
    """
    读取 JSON 文件。
    """
    with input_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def calculate_sha256(file_path: Path) -> str:
    """
    计算文件 SHA256 哈希值。

    作用：
        1. 判断文件是否完整；
        2. 后续可用于去重；
        3. 方便记录数据版本。
    """
    sha256 = hashlib.sha256()

    with file_path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def is_probably_pdf(file_path: Path) -> bool:
    """
    判断文件是否像 PDF。

    PDF 文件一般以：
        %PDF
    开头。

    注意：
        这里只是基础判断，不等于完整 PDF 校验。
    """
    if not file_path.exists() or file_path.stat().st_size == 0:
        return False

    with file_path.open("rb") as file:
        header = file.read(5)

    return header.startswith(b"%PDF")


def get_relative_path(file_path: Path) -> str:
    """
    将文件路径转成相对项目根目录的字符串。

    数据库中建议保存相对路径，而不是绝对路径。
    原因：
        1. 换电脑后路径更容易迁移；
        2. 项目整体移动时不容易失效。
    """
    try:
        return str(file_path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return str(file_path.resolve())


def resolve_project_path(path_value: str | Path) -> Path:
    """
    将数据库中的路径转换为本机绝对路径。

    参数：
        path_value:
            可以是相对路径，例如：
                data/papers/paper_1_xxx.pdf

            也可以是绝对路径，例如：
                D:/work/lit-agent/data/papers/paper_1_xxx.pdf

    返回：
        Path 绝对路径。
    """
    path = Path(path_value)

    if path.is_absolute():
        return path

    return PROJECT_ROOT / path