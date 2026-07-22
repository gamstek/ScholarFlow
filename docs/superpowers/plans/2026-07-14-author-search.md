# AI 作者论文搜索 — 实现方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户能够用 AI 搜索指定作者发表的论文，通过"文献 API 作者查询 + Agent web_search 网页补充"双通道实现。

**Architecture:** 在现有检索管线（API → harvester → pipeline_service → Agent tools）中新增 `author` 参数，各数据源客户端在查询时自动追加作者限定语法；同时为 Agent 新增 `web_search` 工具，通过 DuckDuckGo 免费网页搜索补充 API 覆盖不到的论文来源。Agent 的 LLM 自动编排两路结果、去重、统一呈现。

**Tech Stack:** Python 3.10+ / FastAPI / LangChain Agent / Semantic Scholar API / arXiv API / Europe PMC API / `duckduckgo_search` 库 / React + TypeScript 前端

## Global Constraints

- 保持项目领域中立（不硬编码特定学科）
- 保持 hybrid acquisition path（API 优先，web 补充）
- 使用标准库 `urllib` 风格（与现有客户端一致），web_search 例外可引入轻量依赖
- 前端保持 modern scientific workbench 风格
- 所有修改完成后更新 `dev_log.md`

---

### Task 1: Europe PMC 客户端新增 author 参数

**Files:**
- Modify: `d:\ScholarFlow\app\harvest\literature\europe_pmc_client.py`

**Interfaces:**
- Produces: `EuropePmcClient.search(query, max_results, page_size, enhance_query, enhance_terms, author=None) -> list[PaperMetadata]`

Europe PMC 支持 `AUTH:"Name"` 语法。在 `search()` 中，若 `author` 不为空，将 `AUTH:"{author}"` 拼接到查询字符串前。

- [ ] **Step 1: 修改 `search()` 方法签名，新增 `author` 参数**

修改 `search()` 方法：

```python
def search(
    self,
    query: str,
    max_results: int = 20,
    page_size: int = 25,
    enhance_query: bool = True,
    enhance_terms: list[str] | None = None,
    author: str | None = None,          # 新增
) -> list[PaperMetadata]:
```

- [ ] **Step 2: 在 `search()` 方法体开头拼接 author 限定**

在 `final_query = ...` 之前插入 author 拼接逻辑：

```python
        if author and author.strip():
            query = f'AUTH:"{author.strip()}" {query}'
```

- [ ] **Step 3: 验证修改后的文件无语法错误**

---

### Task 2: arXiv 客户端新增 author 参数

**Files:**
- Modify: `d:\ScholarFlow\app\harvest\literature\arxiv_client.py`

**Interfaces:**
- Produces: `ArxivClient.search(query, max_results, page_size, sort_by, author=None) -> list[PaperMetadata]`

arXiv 支持 `au:Name` 前缀。当前 `_request_search_page` 中 `search_query` 固定为 `all:{query}`。需要改为：若 `author` 不为空，拼入 `au:{author}`。

- [ ] **Step 1: 修改 `search()` 方法签名，新增 `author` 参数**

```python
def search(
    self,
    query: str,
    max_results: int = 20,
    page_size: int = 25,
    sort_by: str = "relevance",
    author: str | None = None,          # 新增
) -> list[PaperMetadata]:
```

- [ ] **Step 2: 修改 `_request_search_page` 的 query 构建逻辑**

将 `_request_search_page` 方法签名也加上 `author`，修改 `search_query` 构建：

```python
    def _request_search_page(
        self,
        query: str,
        start: int,
        page_size: int,
        sort_by: str,
        author: str | None = None,      # 新增
    ) -> str:
```

然后在 `params` 构建处：

```python
        # 构建搜索查询：若有 author，追加 au: 前缀
        if author and author.strip():
            search_query = f'au:"{author.strip()}" AND all:{query}'
        else:
            search_query = f'all:{query}'

        params = {
            "search_query": search_query,
            ...
        }
```

- [ ] **Step 3: 在 `search()` 中传递 `author` 到 `_request_search_page`**

```python
        response_xml = self._request_search_page(
            query=query.strip(),
            start=0,
            page_size=min(page_size, max_results),
            sort_by=sort_by,
            author=author,               # 新增
        )
```

---

### Task 3: Semantic Scholar 客户端新增 author 参数

**Files:**
- Modify: `d:\ScholarFlow\app\harvest\literature\semantic_scholar_client.py`

**Interfaces:**
- Produces: `SemanticScholarClient.search(query, max_results, page_size, year_from, year_to, author=None) -> list[PaperMetadata]`

Semantic Scholar 的 `/paper/search` 端点不支持专用的 author filter，但可以通过将作者名嵌入 query 字符串来近似实现。更好的方式是先调用 `/graph/v1/author/search?query=NAME` 获取 author_id，再调 `/graph/v1/author/{id}/papers`。但为保持与现有架构一致（同步、统一返回 PaperMetadata），MVP 阶段采用 query 内嵌方式。

- [ ] **Step 1: 修改 `search()` 方法签名，新增 `author` 参数**

```python
def search(
    self,
    query: str,
    max_results: int = 20,
    page_size: int = 25,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    author: Optional[str] = None,       # 新增
) -> list[PaperMetadata]:
```

- [ ] **Step 2: 在 search 开头拼接 author 到 query**

```python
        if author and author.strip():
            # Semantic Scholar 支持在 query 中使用引号精确匹配作者名
            query = f'"{author.strip()}" {query}'
```

- [ ] **Step 3: 传递 author 到 `_request_search_page`**

修改 `_request_search_page` 方法内实际使用的 query（当前直接用 `query.strip()`，保持即可，因为上面已拼好）。

---

### Task 4: Harvester + Pipeline Service 透传 author 参数

**Files:**
- Modify: `d:\ScholarFlow\app\harvest\harvester.py`
- Modify: `d:\ScholarFlow\app\services\pipeline_service.py`

**Interfaces:**
- Consumes: `author` from upstream API routes / Agent tools
- Produces: `search_only(query, ..., author=None)`, `search_only_stream(query, ..., author=None)`, `search_papers_service(query, ..., author=None)`, `search_papers_stream_service(query, ..., author=None)`

- [ ] **Step 1: 修改 `_search_one_source` 方法签名和传参**

在 `harvester.py` 的 `_search_one_source` 中新增 `author` 参数，并透传到各客户端：

```python
    def _search_one_source(
        self,
        source: str,
        query: str,
        max_results: int,
        enhance_query: bool,
        enhance_terms: list[str] | None,
        author: str | None = None,      # 新增
    ) -> list[PaperMetadata]:
        """从单个数据源搜索文献。"""
        search_fn = self._get_search_fn(source)

        kwargs: dict[str, Any] = {"query": query, "max_results": max_results}
        if source == "europe_pmc":
            kwargs["enhance_query"] = enhance_query
            kwargs["enhance_terms"] = enhance_terms
        if author:                       # 新增
            kwargs["author"] = author     # 新增

        return search_fn(**kwargs)
```

- [ ] **Step 2: 修改 `search_only` 方法签名**

```python
    async def search_only(
        self,
        query: str,
        sources: list[str] | None = None,
        max_results: int = 20,
        enhance_query: bool = True,
        enhance_terms: list[str] | None = None,
        keywords: list[str] | None = None,
        domain: str | None = None,
        sort_by: str = "relevance",
        sort_order: str = "desc",
        author: str | None = None,       # 新增
    ) -> SearchReport:
```

然后在内部 `_fetch_source` 中传递 `author`：

```python
        async def _fetch_source(source: str) -> tuple[str, list[PaperMetadata], Optional[Exception]]:
            try:
                papers = await asyncio.to_thread(
                    self._search_one_source,
                    source=source,
                    query=query,
                    max_results=max_results,
                    enhance_query=enhance_query,
                    enhance_terms=enhance_terms,
                    author=author,       # 新增
                )
                ...
```

- [ ] **Step 3: 修改 `search_only_stream` 方法签名**（同 search_only 的修改模式）

```python
    async def search_only_stream(
        self,
        ...
        author: str | None = None,       # 新增
    ) -> AsyncGenerator[str, None]:
```

内部 `_fetch_source` 同样传递 `author`。

- [ ] **Step 4: 修改 `pipeline_service.py` 中的两个 service 函数**

`search_papers_service`:

```python
async def search_papers_service(
    query: str,
    sources: list[str] | None = None,
    max_results: int = 20,
    enhance_query: bool = True,
    keywords: list[str] | None = None,
    domain: str | None = None,
    sort_by: str = "relevance",
    sort_order: str = "desc",
    author: str | None = None,           # 新增
) -> dict[str, Any]:
```

内部调用 `harvester.search_only` 时传递 `author=author`。

`search_papers_stream_service`: 同样新增 `author` 参数并透传。

---

### Task 5: Agent search_papers 工具新增 author 参数

**Files:**
- Modify: `d:\ScholarFlow\app\agent\tools.py`

**Interfaces:**
- Produces: `search_papers(query, sources, max_results, author=None) -> str`

- [ ] **Step 1: 修改 `search_papers` 工具函数签名**

```python
@tool
def search_papers(
    query: str,
    sources: str = "europe_pmc",
    max_results: int = 20,
    author: str | None = None,           # 新增
) -> str:
    """
    检索学术论文。输入自然语言或关键词，返回相关论文列表（含评分、DOI、在库状态）。

    参数：
        query: 检索关键词或自然语言描述。
        sources: 数据源，逗号分隔。可选：europe_pmc, nature, science, cell, arxiv, semantic_scholar
        max_results: 每个数据源最大检索数量。
        author: 按作者名过滤。例如 "Geoffrey Hinton"。可选。

    返回：
        JSON 字符串，包含检索结果列表。
    """
```

- [ ] **Step 2: 在 `search_papers_service` 调用处传递 `author`**

```python
    result = asyncio.run(search_papers_service(
        query=search_query,
        sources=source_list,
        max_results=max_results,
        keywords=keywords,
        domain=domain,
        author=author,                   # 新增
    ))
```

---

### Task 6: 创建 web_search 模块和 Agent 工具

**Files:**
- Create: `d:\ScholarFlow\app\agent\web_search.py`
- Modify: `d:\ScholarFlow\app\agent\tools.py`

**Interfaces:**
- Produces: `web_search(query, max_results=10) -> str` (Agent tool)
- Internal: `WebSearcher.search(query, max_results) -> list[dict]`

使用 `duckduckgo_search` 库（免费、无需 API Key），返回标题/摘要/URL 列表。Agent 的 LLM 自行解析网页搜索结果中与作者论文相关的条目。

- [ ] **Step 1: 创建 `web_search.py`**

```python
"""
web_search.py

轻量级网页搜索模块 — 使用 DuckDuckGo 免费搜索 API。

作用：
1. 作为 Agent 的 web_search 工具后端，补充文献 API 覆盖不到的来源；
2. 返回标题、摘要片段、URL 列表，由 Agent LLM 自行解析提取论文信息。

依赖：duckduckgo_search（pip install duckduckgo_search）
"""

from __future__ import annotations

from typing import Any


class WebSearcher:
    """DuckDuckGo 网页搜索器。"""

    def __init__(self, timeout: int = 15, max_retries: int = 2):
        self.timeout = timeout
        self.max_retries = max_retries

    def search(
        self,
        query: str,
        max_results: int = 10,
        region: str = "wt-wt",
    ) -> list[dict[str, str]]:
        """
        执行网页搜索。

        参数：
            query: 搜索查询字符串。
            max_results: 最大返回结果数。
            region: 搜索区域，默认全球。

        返回：
            [{"title": ..., "snippet": ..., "url": ..., "source": ...}, ...]
        """
        if not query or not query.strip():
            return []

        from duckduckgo_search import DDGS

        results: list[dict[str, str]] = []

        for attempt in range(1, self.max_retries + 1):
            try:
                with DDGS(timeout=self.timeout) as ddgs:
                    for r in ddgs.text(
                        keywords=query.strip(),
                        region=region,
                        max_results=max_results,
                    ):
                        results.append({
                            "title": r.get("title", ""),
                            "snippet": r.get("body", ""),
                            "url": r.get("href", ""),
                            "source": "web_search",
                        })
                break
            except Exception:
                if attempt >= self.max_retries:
                    raise

        return results[:max_results]


# 模块级单例
_searcher: WebSearcher | None = None


def get_searcher() -> WebSearcher:
    global _searcher
    if _searcher is None:
        _searcher = WebSearcher()
    return _searcher
```

- [ ] **Step 2: 在 `tools.py` 中添加 `web_search` 工具**

在 `tools.py` 末尾（`ALL_TOOLS` 定义之前）新增：

```python
# ============================================================
# 5. 网页搜索
# ============================================================

@tool
def web_search(
    query: str,
    max_results: int = 10,
) -> str:
    """
    通过网页搜索引擎查找信息。适用于：
    - 搜索特定作者发表的论文（补充文献 API 覆盖不到的来源）
    - 查找论文的个人主页、Google Scholar 档案、机构仓库等
    - 查找 API 数据库未收录的出版物

    参数：
        query: 搜索查询字符串。建议使用 "作者名 论文" 或 "作者名 publications" 格式。
        max_results: 最大返回结果数，默认 10。

    返回：
        JSON 字符串，包含搜索结果的标题、摘要片段和 URL。
    """
    from app.agent.web_search import get_searcher

    searcher = get_searcher()
    results = searcher.search(query=query, max_results=max_results)

    summary = {
        "query": query,
        "total": len(results),
        "results": results,
    }

    return json.dumps(summary, ensure_ascii=False, indent=2)
```

- [ ] **Step 3: 更新 `ALL_TOOLS` 列表**

在 `tools.py` 末尾，将 `web_search` 加入：

```python
ALL_TOOLS = [
    search_papers,
    list_library,
    view_paper,
    ask_paper,
    write_review,
    web_search,          # 新增
]
```

---

### Task 7: 更新 Agent 系统提示词

**Files:**
- Modify: `d:\ScholarFlow\app\agent\agent.py`

**Interfaces:**
- Modifies: `_AGENT_SYSTEM_PROMPT` 常量

- [ ] **Step 1: 更新 `_AGENT_SYSTEM_PROMPT`**

将以下内容替换现有的 `_AGENT_SYSTEM_PROMPT`：

```python
_AGENT_SYSTEM_PROMPT = """你是 ScholarFlow 文献工作站助手。你可以帮助用户检索论文、查看论文全文、回答论文相关问题、撰写文献综述。

你可以使用以下工具：
1. search_papers — 检索学术论文，输入关键词或自然语言描述。支持按作者筛选（author 参数）。
2. list_library — 查看本地已入库的文献列表
3. view_paper — 查看库中论文的全文内容（需要 paper_id）
4. ask_paper — 对本地文献库进行 RAG 问答
5. write_review — 根据主题撰写文献综述
6. web_search — 通过网页搜索引擎查找信息。当用户想"查某人的论文"时，先用 search_papers（带 author 参数）从学术数据库检索，再用 web_search 补充搜索个人主页、Google Scholar 等来源。

使用规则：
- 用户想"找论文"、"搜索"、"检索"时，使用 search_papers
- 用户明确提到"查XX的论文"、"XX发表了什么"、"XX的文章"、"搜作者"时：
  1. 先调用 search_papers（设置 author 参数为提取的作者名）
  2. 同时/随后调用 web_search（query 格式："作者名 publications"或"作者名 papers"）
  3. 整合两路结果，告知用户哪些来自学术数据库、哪些来自网页搜索
- 用户问"库里有什么"、"有哪些论文"、"文献库"时，使用 list_library
- 用户想"看全文"、"读论文"时，先用 list_library 或 search_papers 找到 paper_id，再用 view_paper
- 用户提问论文内容时，使用 ask_paper
- 用户想"写综述"、"总结"时，使用 write_review
- 回答用中文，保留英文专业术语
- 保持简洁，不要过度解释

你可以参考之前的对话历史来理解用户的上下文意图。如果用户说"上面那篇"、"继续找"等指代词，请结合历史消息理解。
"""
```

---

### Task 8: API 路由新增 author 字段

**Files:**
- Modify: `d:\ScholarFlow\app\main.py`

**Interfaces:**
- Modifies: `SearchRequest` Pydantic model, `POST /search`, `POST /search/stream`

- [ ] **Step 1: 在 `SearchRequest` 中新增 `author` 字段**

```python
class SearchRequest(BaseModel):
    """文献检索请求。"""

    query: str = Field(...)
    natural_query: Optional[str] = Field(...)
    sources: list[str] = Field(...)
    max_results: int = Field(...)
    min_domain_score: float = Field(...)
    enhance_query: bool = Field(...)
    sort_by: str = Field(...)
    sort_order: str = Field(...)
    author: Optional[str] = Field(        # 新增
        None,
        description="按作者名过滤。例如 'Geoffrey Hinton'。",
    )
```

- [ ] **Step 2: 在 `/search` 端点传递 `author`**

```python
        result = await search_papers_service(
            query=query,
            sources=request.sources,
            max_results=request.max_results,
            enhance_query=request.enhance_query,
            keywords=keywords,
            domain=domain,
            sort_by=request.sort_by,
            sort_order=request.sort_order,
            author=request.author,         # 新增
        )
```

- [ ] **Step 3: 在 `/search/stream` 端点同样传递 `author`**

```python
            async for event in search_papers_stream_service(
                query=query,
                sources=request.sources,
                max_results=request.max_results,
                enhance_query=request.enhance_query,
                keywords=keywords,
                domain=domain,
                sort_by=request.sort_by,
                sort_order=request.sort_order,
                author=request.author,     # 新增
            ):
```

---

### Task 9: 前端 SearchPage 新增作者输入框

**Files:**
- Modify: `d:\ScholarFlow\frontend\src\pages\SearchPage.tsx`
- Modify: `d:\ScholarFlow\frontend\src\lib\api.ts`

**Interfaces:**
- Produces: SearchPage 中新增 `author` 输入框，`api.search()` 传递 `author` 参数

- [ ] **Step 1: 在 `api.ts` 的 `search()` 函数中新增 `author` 参数**

找到 `api` 对象中的 `search` 方法（或 `searchStream`），新增 `author` 参数：

```typescript
  /** 文献检索（仅检索不入库） */
  async search(params: {
    query?: string;
    natural_query?: string;
    sources?: string[];
    max_results?: number;
    sort_by?: string;
    sort_order?: string;
    author?: string;             // 新增
  }): Promise<SearchResult> {
    return post<SearchResult>('/search', {
      query: params.query || '',
      natural_query: params.natural_query || null,
      sources: params.sources || ['europe_pmc'],
      max_results: params.max_results || 20,
      sort_by: params.sort_by || 'relevance',
      sort_order: params.sort_order || 'desc',
      author: params.author || null,  // 新增
    });
  },
```

- [ ] **Step 2: 在 `SearchPage.tsx` 中新增 `author` 状态和输入框**

在 `SearchPage` 组件中添加 `author` state：

```typescript
  const [author, setAuthor] = useState('');
```

在 localStorage 持久化逻辑中补上 `author` 的保存和恢复。

在搜索表单中（`sources` 选择器下方或 `query` 输入框旁边）添加作者输入框：

```tsx
          {/* 作者筛选 */}
          <div className="search-author-row">
            <User size={16} />
            <input
              type="text"
              className="author-input"
              placeholder="按作者筛选（可选），如 Geoffrey Hinton"
              value={author}
              onChange={(e) => setAuthor(e.target.value)}
            />
            {author && (
              <button
                className="clear-author-btn"
                onClick={() => setAuthor('')}
                title="清除作者筛选"
              >
                <X size={14} />
              </button>
            )}
          </div>
```

- [ ] **Step 3: 在发起搜索时传递 `author`**

在 `handleSearch` 函数中，调用 `api.search()` 或 `api.searchStream()` 时传入 `author`：

```typescript
    const result = await api.search({
      query: mode === 'keyword' ? query : undefined,
      natural_query: mode === 'natural' ? naturalQuery : undefined,
      sources,
      max_results: maxResults,
      sort_by: sortBy,
      sort_order: sortOrder,
      author: author || undefined,   // 新增
    });
```

- [ ] **Step 4: 补充 `User` 和 `X` 图标的 import**（如果 `lucide-react` 已导入）

检查 `lucide-react` import 中是否已有 `User` 和 `X`，如无则补充。

---

### Task 10: 安装 duckduckgo_search 依赖并更新 requirements

**Files:**
- Modify: `d:\ScholarFlow\requirements\requirements.txt`
- Modify: `d:\ScholarFlow\requirements\requirements-rtx30.txt`
- Modify: `d:\ScholarFlow\requirements\requirements-rtx40.txt`
- Modify: `d:\ScholarFlow\requirements\requirements-rtx50.txt`

- [ ] **Step 1: 在各 requirements 文件中添加依赖**

在四个 requirements 文件末尾各添加一行：

```
duckduckgo_search>=7.0.0
```

- [ ] **Step 2: 安装依赖**

```bash
pip install duckduckgo_search
```

---

### Task 11: 更新 dev_log.md

**Files:**
- Modify: `d:\ScholarFlow\dev_log.md`

- [ ] **Step 1: 在开发时间线中追加记录**

```markdown
## 开发时间线

...
- `代码生成(harvester/clients)`: Europe PMC / arXiv / Semantic Scholar 客户端新增 author 参数，支持按作者名过滤检索
- `代码生成(agent)`: 新增 web_search 工具模块（DuckDuckGo），Agent 可并行调用文献 API + 网页搜索查找作者论文
- `代码生成(agent)`: 更新 Agent 系统提示词，编排 author search + web_search 双通道作者论文查询
- `代码生成(api)`: SearchRequest 模型新增 author 字段，/search 和 /search/stream 端点透传作者参数
- `代码生成(frontend)`: SearchPage 新增作者输入框，支持按作者名筛选检索结果
```

---

## Self-Review

**1. Spec coverage:**
- ✅ 作者名在文献 API 中的查询支持（Task 1-4）
- ✅ Agent web_search 工具（Task 6）
- ✅ Agent 编排双通道（Task 7）
- ✅ API 路由透传（Task 8）
- ✅ 前端搜索 UI（Task 9）
- ✅ 依赖管理（Task 10）

**2. Placeholder scan:** 无 TBD/TODO/占位符，所有步骤包含具体代码。

**3. Type consistency:**
- `author: str | None = None` 在所有层级保持一致
- `SearchRequest.author: Optional[str]` 与 Pydantic 模型一致
- 前端 `author?: string` 与 TypeScript 类型一致
