"""
chunker.py

论文正文切分模块 Text Chunker。

作用：
1. 读取 PDF 解析后的结构化 JSON；
2. 优先按 section 切分；
3. 将长 section 切成适合 RAG 的 chunk；
4. 保留 paper_id、section_title、page_start、page_end 等元数据；
5. 为后续 embedding / FAISS 检索做准备。

为什么要切 chunk？
    大模型不能一次性处理整篇论文；
    向量检索也不能直接把整篇论文作为一个向量；
    所以需要把论文拆成语义相对完整的小块。

当前策略：
    section-based chunking + paragraph packing + character overlap

即：
    先按章节切；
    每个章节内按段落组合；
    超过 max_chars 后形成一个 chunk；
    chunk 之间保留 overlap，避免上下文断裂。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class TextChunk:
    """
    文本 chunk 数据结构。

    字段说明：
        chunk_index:
            当前论文内部的 chunk 编号，从 0 开始。

        section_title:
            所属章节标题。

        page_start:
            起始页码。

        page_end:
            结束页码。

        text:
            chunk 正文。

        token_count:
            粗略 token 数估计。
    """

    chunk_index: int
    section_title: Optional[str]
    page_start: Optional[int]
    page_end: Optional[int]
    text: str
    token_count: int


class SectionBasedChunker:
    """
    基于章节的论文文本切分器。

    参数：
        max_chars:
            每个 chunk 最大字符数。
            对英文论文，建议 1800~3000。
            当前默认 2500，适合 BGE + RAG 初版。

        overlap_chars:
            相邻 chunk 之间保留的重叠字符数。
            避免上下文被硬切断。

        min_chars:
            过短 chunk 的最小字符数。
            低于该长度的片段会尽量和前后合并。

        skip_reference_sections:
            是否跳过 References / Acknowledgements 等低价值章节。
    """

    def __init__(
        self,
        max_chars: int = 2500,
        overlap_chars: int = 300,
        min_chars: int = 300,
        skip_reference_sections: bool = True,
    ) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars 必须大于 0。")

        if overlap_chars < 0:
            raise ValueError("overlap_chars 不能为负数。")

        if overlap_chars >= max_chars:
            raise ValueError("overlap_chars 必须小于 max_chars。")

        self.max_chars = max_chars
        self.overlap_chars = overlap_chars
        self.min_chars = min_chars
        self.skip_reference_sections = skip_reference_sections

    def chunk_parsed_document(
        self,
        parsed_json: dict[str, Any],
    ) -> list[TextChunk]:
        """
        将解析后的论文 JSON 切成 chunks。

        参数：
            parsed_json:
                第五步保存到 data/texts/*.json 的结构化正文。

        返回：
            TextChunk 列表。
        """
        sections = parsed_json.get("sections") or []

        if sections:
            chunks = self._chunk_from_sections(sections)
        else:
            # 如果章节识别失败，则退回到按页切分
            pages = parsed_json.get("pages") or []
            chunks = self._chunk_from_pages(pages)

        return self._reindex_chunks(chunks)

    def _chunk_from_sections(
        self,
        sections: list[dict[str, Any]],
    ) -> list[TextChunk]:
        """
        基于 sections 切分。
        """
        all_chunks: list[TextChunk] = []

        for section in sections:
            section_title = section.get("section_title") or "Unknown"
            page_start = section.get("page_start")
            page_end = section.get("page_end")
            text = clean_chunk_text(section.get("text") or "")

            if not text:
                continue

            if self.skip_reference_sections and is_low_value_section(section_title):
                continue

            section_chunks = self._split_text_into_chunks(
                text=text,
                section_title=section_title,
                page_start=page_start,
                page_end=page_end,
            )

            all_chunks.extend(section_chunks)

        return all_chunks

    def _chunk_from_pages(
        self,
        pages: list[dict[str, Any]],
    ) -> list[TextChunk]:
        """
        如果没有 sections，则基于 pages 切分。
        """
        pseudo_sections: list[dict[str, Any]] = []

        for page in pages:
            page_number = page.get("page_number")
            text = clean_chunk_text(page.get("text") or "")

            if not text:
                continue

            pseudo_sections.append(
                {
                    "section_title": "Unknown",
                    "page_start": page_number,
                    "page_end": page_number,
                    "text": text,
                }
            )

        return self._chunk_from_sections(pseudo_sections)

    def _split_text_into_chunks(
        self,
        text: str,
        section_title: Optional[str],
        page_start: Optional[int],
        page_end: Optional[int],
    ) -> list[TextChunk]:
        """
        将单个 section 的长文本切分为多个 chunks。

        策略：
            1. 按段落切分；
            2. 尽量把多个段落合并成接近 max_chars 的 chunk；
            3. 如果单个段落过长，则按句子进一步切分；
            4. chunk 之间保留 overlap。
        """
        paragraphs = split_into_paragraphs(text)

        # 如果没有明显段落，则退回句子切分
        if not paragraphs:
            paragraphs = split_into_sentences(text)

        # 将过长段落拆小
        normalized_units: list[str] = []
        for paragraph in paragraphs:
            if len(paragraph) <= self.max_chars:
                normalized_units.append(paragraph)
            else:
                normalized_units.extend(
                    split_long_text(
                        text=paragraph,
                        max_chars=self.max_chars,
                    )
                )

        chunks: list[TextChunk] = []
        current_parts: list[str] = []
        current_length = 0

        for unit in normalized_units:
            unit = unit.strip()
            if not unit:
                continue

            unit_length = len(unit)

            # 如果当前 chunk 为空，直接放入
            if not current_parts:
                current_parts.append(unit)
                current_length = unit_length
                continue

            # 如果加入该段后不超过 max_chars，则继续合并
            if current_length + 2 + unit_length <= self.max_chars:
                current_parts.append(unit)
                current_length += 2 + unit_length
                continue

            # 否则，先保存当前 chunk
            chunk_text = "\n\n".join(current_parts).strip()

            if chunk_text:
                chunks.append(
                    self._make_chunk(
                        text=chunk_text,
                        section_title=section_title,
                        page_start=page_start,
                        page_end=page_end,
                    )
                )

            # 构造 overlap 文本
            overlap_text = get_tail_overlap(
                text=chunk_text,
                overlap_chars=self.overlap_chars,
            )

            current_parts = []
            current_length = 0

            if overlap_text:
                current_parts.append(overlap_text)
                current_length += len(overlap_text)

            current_parts.append(unit)
            current_length += 2 + unit_length

        # 保存最后一个 chunk
        final_text = "\n\n".join(current_parts).strip()

        if final_text:
            chunks.append(
                self._make_chunk(
                    text=final_text,
                    section_title=section_title,
                    page_start=page_start,
                    page_end=page_end,
                )
            )

        # 如果某 section 被切出很多很短 chunk，做一次简单合并
        chunks = self._merge_tiny_chunks(chunks)

        return chunks

    def _make_chunk(
        self,
        text: str,
        section_title: Optional[str],
        page_start: Optional[int],
        page_end: Optional[int],
    ) -> TextChunk:
        """
        创建 TextChunk。
        chunk_index 先临时置为 -1，最后统一重排。
        """
        cleaned = clean_chunk_text(text)

        return TextChunk(
            chunk_index=-1,
            section_title=section_title,
            page_start=page_start,
            page_end=page_end,
            text=cleaned,
            token_count=estimate_token_count(cleaned),
        )

    def _merge_tiny_chunks(
        self,
        chunks: list[TextChunk],
    ) -> list[TextChunk]:
        """
        合并过短 chunk。

        目的：
            减少碎片化。
            过短 chunk 向量语义不稳定，检索效果可能差。
        """
        if not chunks:
            return []

        merged: list[TextChunk] = []

        for chunk in chunks:
            if (
                merged
                and len(chunk.text) < self.min_chars
                and len(merged[-1].text) + 2 + len(chunk.text) <= self.max_chars
                and merged[-1].section_title == chunk.section_title
            ):
                new_text = clean_chunk_text(
                    merged[-1].text + "\n\n" + chunk.text
                )

                merged[-1] = TextChunk(
                    chunk_index=-1,
                    section_title=merged[-1].section_title,
                    page_start=merged[-1].page_start,
                    page_end=chunk.page_end or merged[-1].page_end,
                    text=new_text,
                    token_count=estimate_token_count(new_text),
                )
            else:
                merged.append(chunk)

        return merged

    def _reindex_chunks(
        self,
        chunks: list[TextChunk],
    ) -> list[TextChunk]:
        """
        重新编号 chunk_index。
        """
        reindexed: list[TextChunk] = []

        for index, chunk in enumerate(chunks):
            reindexed.append(
                TextChunk(
                    chunk_index=index,
                    section_title=chunk.section_title,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    text=chunk.text,
                    token_count=chunk.token_count,
                )
            )

        return reindexed


def clean_chunk_text(text: str) -> str:
    """
    清洗 chunk 文本。

    处理：
        1. 去掉首尾空白；
        2. 合并过多空行；
        3. 合并行内多余空格；
        4. 去掉明显页码噪声。
    """
    if not text:
        return ""

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # 合并行内多余空格
    text = re.sub(r"[ \t]+", " ", text)

    # 去除孤立页码行
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()

        # 单独一行数字，通常是页码
        if re.fullmatch(r"\d{1,4}", stripped):
            continue

        lines.append(stripped)

    text = "\n".join(lines)

    # 合并 3 个以上连续换行
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def split_into_paragraphs(text: str) -> list[str]:
    """
    按段落切分文本。

    优先使用空行作为段落分隔。
    """
    text = clean_chunk_text(text)

    if not text:
        return []

    paragraphs = re.split(r"\n\s*\n", text)

    paragraphs = [
        paragraph.strip()
        for paragraph in paragraphs
        if paragraph.strip()
    ]

    return paragraphs


def split_into_sentences(text: str) -> list[str]:
    """
    简单英文句子切分。

    注意：
        这是规则版，不追求完美。
        主要用于处理没有明显段落的 PDF 文本。
    """
    text = clean_chunk_text(text)

    if not text:
        return []

    # 按英文句号、问号、感叹号后面的空格切
    sentences = re.split(r"(?<=[.!?])\s+", text)

    return [
        sentence.strip()
        for sentence in sentences
        if sentence.strip()
    ]


def split_long_text(
    text: str,
    max_chars: int,
) -> list[str]:
    """
    将超长文本切成多个不超过 max_chars 的片段。

    优先按句子切分；如果句子仍过长，再硬切。
    """
    sentences = split_into_sentences(text)

    if not sentences:
        return hard_split_text(text, max_chars=max_chars)

    chunks: list[str] = []
    current_parts: list[str] = []
    current_length = 0

    for sentence in sentences:
        if len(sentence) > max_chars:
            if current_parts:
                chunks.append(" ".join(current_parts).strip())
                current_parts = []
                current_length = 0

            chunks.extend(
                hard_split_text(
                    text=sentence,
                    max_chars=max_chars,
                )
            )
            continue

        if not current_parts:
            current_parts.append(sentence)
            current_length = len(sentence)
            continue

        if current_length + 1 + len(sentence) <= max_chars:
            current_parts.append(sentence)
            current_length += 1 + len(sentence)
        else:
            chunks.append(" ".join(current_parts).strip())
            current_parts = [sentence]
            current_length = len(sentence)

    if current_parts:
        chunks.append(" ".join(current_parts).strip())

    return [
        chunk
        for chunk in chunks
        if chunk
    ]


def hard_split_text(
    text: str,
    max_chars: int,
) -> list[str]:
    """
    硬切长文本。

    只有在段落/句子切分都无法处理时使用。
    """
    text = clean_chunk_text(text)

    if not text:
        return []

    return [
        text[index:index + max_chars].strip()
        for index in range(0, len(text), max_chars)
        if text[index:index + max_chars].strip()
    ]


def get_tail_overlap(
    text: str,
    overlap_chars: int,
) -> str:
    """
    获取上一个 chunk 尾部 overlap 文本。

    为了避免从句子中间截断，先取尾部字符，再尝试从最近的句号后开始。
    """
    if overlap_chars <= 0:
        return ""

    if len(text) <= overlap_chars:
        return text

    tail = text[-overlap_chars:].strip()

    # 尝试从最近的句子边界开始
    match = re.search(r"(?<=[.!?])\s+", tail)

    if match:
        tail = tail[match.end():].strip()

    return tail


def estimate_token_count(text: str) -> int:
    """
    粗略估计 token 数。

    英文论文中，通常 1 token 约等于 3~5 个字符。
    这里用保守估计：
        token_count ≈ 字符数 / 4

    注意：
        这不是精确 tokenizer。
        后续如果要严格控制上下文长度，可以接入 tiktoken 或模型 tokenizer。
    """
    if not text:
        return 0

    return max(1, int(len(text) / 4))


def is_low_value_section(section_title: Optional[str]) -> bool:
    """
    判断是否为低价值章节。

    默认跳过：
        References
        Acknowledgements
        Author Contributions
        Conflict of Interest
        Supplementary Material

    原因：
        这些内容对 RAG 问答帮助较小，
        还会污染检索结果。
    """
    if not section_title:
        return False

    title = section_title.lower().strip()

    low_value_terms = [
        "references",
        "reference",
        "acknowledgement",
        "acknowledgment",
        "acknowledgements",
        "acknowledgments",
        "author contributions",
        "conflict of interest",
        "competing interests",
        "funding",
        "supplementary material",
        "supplemental material",
    ]

    return any(term in title for term in low_value_terms)