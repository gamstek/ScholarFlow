# 作者搜索 + 机构筛选 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增机构（institution）筛选功能，支持按作者机构搜索文献；入库时存储机构信息；前端提供本地库机构排名预设列表。

**Architecture:** 在现有 `author` 参数管线旁新增 `institution` 参数。OpenAlex/PubMed 客户端解析机构数据并支持机构过滤；新增 `author_utils.py` 处理 `authors_json` 向后兼容解析；新增 `GET /institutions` 端点从本地库聚合机构排名。

**Tech Stack:** Python 3.10+ / FastAPI / SQLAlchemy / React + TypeScript

## Global Constraints

- 保持项目领域中性（domain-agnostic）
- `authors_json` 格式升级必须向后兼容旧 `list[str]` 数据
- 机构筛选 best-effort：不支持的数据源静默跳过机构参数
- 前端保持 indigo 色系 + 现代科技感
- 变更后更新 `dev_log.md`

---

## 文件结构

| 文件 | 职责 | 变更类型 |
|------|------|----------|
| `app/harvest/literature/author_utils.py` | 向后兼容解析/格式化 `authors_json` | **新建** |
| `app/harvest/literature/europe_pmc_client.py` | `PaperMetadata` 新增 `author_affiliations` 字段 | 修改 |
| `app/harvest/literature/openalex_client.py` | 解析 `authorships[].institutions[]`；新增 `institution` 搜索参数 | 修改 |
| `app/harvest/literature/pubmed_client.py` | 新增 `[AD]` 机构检索；解析 `affiliation` 信息 | 修改 |
| `app/harvest/harvester.py` | `SearchHit` 新增 `author_affiliations`；`_search_one_source` 透传 `institution` | 修改 |
| `app/services/pipeline_service.py` | `search_papers_service` / `search_papers_stream_service` 透传 `institution` | 修改 |
| `app/main.py` | `SearchRequest` 新增 `institution`；新增 `GET /institutions` 端点 | 修改 |
| `frontend/src/lib/api.ts` | 类型 + `search()` 参数新增 `institution`；新增 `getInstitutions()` | 修改 |
| `frontend/src/pages/SearchPage.tsx` | 机构输入框 UI + 预设下拉列表 | 修改 |

---

### Task 1: 创建 `author_utils.py` — 向后兼容解析器

**Files:**
- Create: `d:\ScholarFlow\app\harvest\literature\author_utils.py`

**Interfaces:**
- Produces: `parse_authors_json(authors_json: str | None) -> list[dict]`
- Produces: `format_authors_json(authors: list[dict]) -> str`
- Produces: `authors_to_strings(authors: list[dict]) -> list[str]`

- [ ] **Step 1: 创建文件并写入完整代码**

```python
"""
author_utils.py

向后兼容的作者数据解析工具。

旧格式：authors_json = ["John Smith", "Jane Doe"]
新格式：authors_json = [{"name": "John Smith", "institution": "MIT"}, ...]

本模块提供统一的解析/格式化接口，确保旧数据无缝兼容。
"""

from __future__ import annotations

import json
from typing import Any, Optional


def parse_authors_json(authors_json: Optional[str]) -> list[dict[str, Optional[str]]]:
    """
    向后兼容解析 authors_json 字段。

    旧格式（list[str]）自动升级为新格式（list[dict]）。
    返回：
        [{"name": "...", "institution": "..." or None}, ...]
    """
    if not authors_json:
        return []

    try:
        data = json.loads(authors_json)
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(data, list):
        return []

    result: list[dict[str, Optional[str]]] = []
    for item in data:
        if isinstance(item, str):
            result.append({"name": item, "institution": None})
        elif isinstance(item, dict):
            result.append({
                "name": item.get("name", ""),
                "institution": item.get("institution"),
            })
        else:
            result.append({"name": str(item), "institution": None})

    return result


def format_authors_json(authors: list[dict[str, Optional[str]]]) -> str:
    """
    将结构化作者列表序列化为 JSON 字符串。

    去除空字符串和 None 值的 institution 字段以减小存储。
    """
    cleaned: list[dict[str, Any]] = []
    for a in authors:
        entry: dict[str, Any] = {"name": a.get("name", "")}
        inst = a.get("institution")
        if inst:
            entry["institution"] = inst
        cleaned.append(entry)
    return json.dumps(cleaned, ensure_ascii=False)


def authors_to_strings(authors: list[dict[str, Optional[str]]]) -> list[str]:
    """提取作者名列表（纯字符串），供旧接口兼容使用。"""
    return [a.get("name", "") for a in authors if a.get("name")]
```

- [ ] **Step 2: 验证语法**

Run: `python -c "from app.harvest.literature.author_utils import parse_authors_json, format_authors_json, authors_to_strings; print('OK')"`

---

### Task 2: 扩展 `PaperMetadata` — 新增 `author_affiliations`

**Files:**
- Modify: `d:\ScholarFlow\app\harvest\literature\europe_pmc_client.py`

**Interfaces:**
- Modifies: `PaperMetadata` dataclass → 新增 `author_affiliations: Optional[list[dict]] = None`

- [ ] **Step 1: 在 `PaperMetadata` dataclass 中新增字段**

在 `europe_pmc_client.py` 中找到 `@dataclass class PaperMetadata:`，在 `authors` 字段后新增：

```python
@dataclass
class PaperMetadata:
    """单篇文献的标准化 metadata。"""

    title: str
    abstract: Optional[str] = None
    authors: Optional[list[str]] = None
    author_affiliations: Optional[list[dict]] = None  # 新增：[{name, institution}]
    year: Optional[int] = None
    # ... 其余字段不变 ...
```

- [ ] **Step 2: 验证**

Run: `python -c "from app.harvest.literature.europe_pmc_client import PaperMetadata; p = PaperMetadata(title='test', author_affiliations=[{'name':'A','institution':'MIT'}]); print(p.author_affiliations)"`

---

### Task 3: OpenAlex 客户端 — 解析机构 + 机构过滤

**Files:**
- Modify: `d:\ScholarFlow\app\harvest\literature\openalex_client.py`

**Interfaces:**
- Modifies: `search()` → 新增 `institution: str | None = None`
- Modifies: `_parse_work()` → 提取 `authorships[].institutions[]`

- [ ] **Step 1: 修改 `search()` 方法签名，新增 `institution` 参数**

```python
    def search(
        self,
        query: str,
        max_results: int = 20,
        per_page: int = 25,
        author: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        preprint_sources: list[str] | None = None,
        institution: str | None = None,          # 新增
    ) -> list[PaperMetadata]:
```

- [ ] **Step 2: 在 `search()` 的 filter 构建处新增 institution 过滤**

在现有 `if author and author.strip():` 块之后，`if preprint_sources:` 之前，新增：

```python
            if institution and institution.strip():
                # OpenAlex 全文搜索会覆盖 institution 名称
                # filter 级别用 raw_affiliation_string.search 做模糊匹配
                filters.append(f"raw_affiliation_string.search:{institution.strip()}")
```

- [ ] **Step 3: 修改 `_parse_work()` 提取机构信息**

将现有的作者解析部分（约第 149-154 行）替换为：

```python
        # 作者 + 机构
        authorship = item.get("authorships", [])
        authors: list[str] = []
        author_affiliations: list[dict] = []
        for a in authorship:
            author_info = a.get("author", {}) or {}
            name = author_info.get("display_name", "")
            if name:
                authors.append(name)
                # 提取机构
                institutions = a.get("institutions", []) or []
                inst_names = [i.get("display_name", "") for i in institutions if i.get("display_name")]
                inst_str = "; ".join(inst_names) if inst_names else None
                author_affiliations.append({"name": name, "institution": inst_str})
```

- [ ] **Step 4: 在 `return PaperMetadata(...)` 中传入 `author_affiliations`**

在 `_parse_work()` 返回处，新增 `author_affiliations=author_affiliations if author_affiliations else None`：

```python
        return PaperMetadata(
            title=title,
            abstract=abstract,
            authors=authors if authors else None,
            author_affiliations=author_affiliations if author_affiliations else None,
            year=year,
            # ... 其余不变 ...
        )
```

- [ ] **Step 5: 验证**

Run: `python -c "from app.harvest.literature.openalex_client import OpenAlexClient; print('OK')"`

---

### Task 4: PubMed 客户端 — `[AD]` 检索 + affiliation 解析

**Files:**
- Modify: `d:\ScholarFlow\app\harvest\literature\pubmed_client.py`

**Interfaces:**
- Modifies: `search()` → 新增 `institution: str | None = None`
- Modifies: `_parse_result_item()` → 提取 `affiliation`

- [ ] **Step 1: 修改 `search()` 方法签名**

```python
    def search(
        self,
        query: str,
        max_results: int = 20,
        author: str | None = None,
        institution: str | None = None,          # 新增
    ) -> list[PaperMetadata]:
```

- [ ] **Step 2: 在查询构建中新增 `[AD]` 支持**

在 `search()` 方法中，`if author and author.strip():` 块之后新增：

```python
        if institution and institution.strip():
            search_terms.append(f'{institution.strip()}[AD]')
```

- [ ] **Step 3: 修改 `_parse_result_item()` 提取 affiliation**

在现有 `authors` 解析处（~154-156行），改为同时提取机构：

```python
            # 作者 + 机构
            authors_raw = item.get("authors", [])
            authors: list[str] = []
            author_affiliations: list[dict] = []
            for a in authors_raw:
                name = a.get("name", "")
                if name:
                    authors.append(name)
                    aff = a.get("affiliation") or None
                    author_affiliations.append({"name": name, "institution": aff})
```

- [ ] **Step 4: 在 `return PaperMetadata(...)` 中传入 `author_affiliations`**

```python
                authors=authors if authors else None,
                author_affiliations=author_affiliations if author_affiliations else None,
```

- [ ] **Step 5: 验证**

Run: `python -c "from app.harvest.literature.pubmed_client import PubmedClient; print('OK')"`

---

### Task 5: Harvester — `SearchHit` + `_search_one_source` 透传

**Files:**
- Modify: `d:\ScholarFlow\app\harvest\harvester.py`

**Interfaces:**
- Modifies: `SearchHit` → 新增 `author_affiliations: Optional[list[dict]] = None`
- Modifies: `_search_one_source()` → 新增 `institution` 参数透传
- Modifies: `search_only()` → 新增 `institution` 参数 + 填充 SearchHit
- Modifies: `search_only_stream()` → 同上

- [ ] **Step 1: 在 `SearchHit` dataclass 中新增字段**

```python
@dataclass
class SearchHit:
    """单条检索结果（不入库，仅返回给前端预览）。"""

    title: str
    abstract: Optional[str]
    authors: Optional[list[str]]
    author_affiliations: Optional[list[dict]]   # 新增
    year: Optional[int]
    # ... 其余字段不变 ...
```

- [ ] **Step 2: 修改 `search_only()` 签名**

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
        author: str | None = None,
        journal: str | None = None,
        preprint_sources: list[str] | None = None,
        institution: str | None = None,          # 新增
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> SearchReport:
```

- [ ] **Step 3: 修改 `_fetch_source` 内部调用，透传 `institution`**

```python
                papers = await asyncio.to_thread(
                    self._search_one_source,
                    source=source,
                    query=query,
                    max_results=max_results,
                    enhance_query=enhance_query,
                    enhance_terms=enhance_terms,
                    author=author,
                    journal=journal,
                    preprint_sources=preprint_sources,
                    institution=institution,      # 新增
                )
```

- [ ] **Step 4: 修改 `_search_one_source()` 透传 `institution`**

```python
    def _search_one_source(
        self,
        source: str,
        query: str,
        max_results: int,
        enhance_query: bool,
        enhance_terms: list[str] | None,
        author: str | None = None,
        journal: str | None = None,
        preprint_sources: list[str] | None = None,
        institution: str | None = None,          # 新增
    ) -> list[PaperMetadata]:
```

并在 kwargs 构建处新增：

```python
        if institution:
            kwargs["institution"] = institution
```

- [ ] **Step 5: 在构造 `SearchHit` 时填充 `author_affiliations`**

在 `results.append(SearchHit(...))` 处新增：

```python
            results.append(SearchHit(
                title=paper.title,
                abstract=paper.abstract,
                authors=paper.authors,
                author_affiliations=paper.author_affiliations,  # 新增
                year=paper.year,
                # ... 其余不变 ...
            ))
```

两处 `search_only()` 和 `search_only_stream()` 的 `SearchHit` 构造都需要改。

- [ ] **Step 6: 同步修改 `search_only_stream()`**

`search_only_stream()` 方法同样需要：签名加 `institution`，`_fetch_source` 加 `institution`，`SearchHit` 加 `author_affiliations`。

- [ ] **Step 7: 同步修改 `crawl()` 方法中的 `SearchHit` 构造（如有）**

搜索 `SearchHit(` 确保所有构造处都加上 `author_affiliations=paper.author_affiliations`。

- [ ] **Step 8: 修改 `report_to_dict` 和 `search_report_to_dict` 序列化**

如果有 `report_to_dict` 和 `search_report_to_dict` 函数序列化 SearchHit，确保 `author_affiliations` 字段被序列化：

```python
                    "author_affiliations": h.author_affiliations,
```

- [ ] **Step 9: 验证**

Run: `python -c "from app.harvest.harvester import LiteratureHarvester, SearchHit; print('OK')"`

---

### Task 6: Pipeline Service — 参数透传

**Files:**
- Modify: `d:\ScholarFlow\app\services\pipeline_service.py`

**Interfaces:**
- Modifies: `search_papers_service()` → 新增 `institution`
- Modifies: `search_papers_stream_service()` → 新增 `institution`

- [ ] **Step 1: 修改 `search_papers_service()` 签名和调用**

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
    author: str | None = None,
    journal: str | None = None,
    preprint_sources: list[str] | None = None,
    institution: str | None = None,              # 新增
) -> dict[str, Any]:
```

在 `harvester.search_only()` 调用处新增 `institution=institution`。

- [ ] **Step 2: 同步修改 `search_papers_stream_service()`**

同样加 `institution` 参数并透传。

- [ ] **Step 3: 验证**

Run: `python -c "from app.services.pipeline_service import search_papers_service; print('OK')"`

---

### Task 7: `main.py` — `SearchRequest` + `GET /institutions`

**Files:**
- Modify: `d:\ScholarFlow\app\main.py`

**Interfaces:**
- Modifies: `SearchRequest` → 新增 `institution: Optional[str] = None`
- Creates: `GET /institutions` 端点

- [ ] **Step 1: 在 `SearchRequest` 中新增 `institution` 字段**

```python
class SearchRequest(BaseModel):
    # ... 现有字段 ...
    institution: Optional[str] = Field(
        None,
        description="按机构名筛选。例如 'MIT' 或 'CSAIL'。仅 OpenAlex / PubMed 生效。",
    )
```

- [ ] **Step 2: 在 `/search` 路由中透传 `institution`**

找到 `search_papers_service()` 调用处，新增 `institution=request.institution`：

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
            author=request.author,
            journal=request.journal,
            preprint_sources=request.preprint_sources,
            institution=request.institution,      # 新增
        )
```

- [ ] **Step 3: 同步修改 `/search/stream` 路由**

同样在 `search_papers_stream_service()` 调用处新增 `institution=request.institution`。

- [ ] **Step 4: 新增 `GET /institutions` 端点**

在 `main.py` 中合适位置（如 `/stats` 之后）新增：

```python
@app.get("/institutions")
async def list_institutions(
    limit: int = Query(20, ge=1, le=50),
) -> dict[str, Any]:
    """
    返回本地文献库中机构排名（按出现频率降序）。

    从 papers.authors_json 提取所有 institution 字段，聚合计数。
    """
    from app.harvest.literature.author_utils import parse_authors_json

    paper_repo = PaperRepository()

    # 获取所有有 authors_json 的论文
    async with async_session_factory() as session:
        from app.storage.models import Paper as PaperModel
        from sqlalchemy import select as sa_select

        result = await session.execute(
            sa_select(PaperModel.authors_json).where(PaperModel.authors_json.isnot(None))
        )
        rows = result.fetchall()

    counter: dict[str, int] = {}
    for row in rows:
        authors = parse_authors_json(row[0])
        for a in authors:
            inst = a.get("institution")
            if inst:
                # 处理多机构情况（分号分隔）
                for part in inst.split(";"):
                    part = part.strip()
                    if part:
                        counter[part] = counter.get(part, 0) + 1

    sorted_insts = sorted(counter.items(), key=lambda x: x[1], reverse=True)
    top = [{"name": k, "count": v} for k, v in sorted_insts[:limit]]

    return {
        "institutions": top,
        "total_unique": len(counter),
    }
```

- [ ] **Step 5: 修改入库流程（crawl 写入 DB 时存储机构）**

找到 `harvester.py` 中 `crawl()` 方法写入数据库的位置，修改 `authors_json` 的写入：

```python
# 旧代码（示例）：
# authors_json = json.dumps(paper.authors) if paper.authors else None

# 新代码：
from app.harvest.literature.author_utils import format_authors_json, parse_authors_json

if paper.author_affiliations:
    authors_json = format_authors_json(paper.author_affiliations)
elif paper.authors:
    # 仅有作者名无机构时，生成旧兼容格式
    authors_json = json.dumps(paper.authors)
else:
    authors_json = None
```

需要找到 `harvester.py` 中 `crawl()` 方法里实际写入 `authors_json` 的位置并修改。

- [ ] **Step 6: 验证**

Run: `python -c "from app.main import app; print('OK')"`

---

### Task 8: 前端 `api.ts` — 类型 + 参数

**Files:**
- Modify: `d:\ScholarFlow\frontend\src\lib\api.ts`

**Interfaces:**
- Modifies: `SearchHit` → 新增 `author_affiliations`
- Modifies: `api.search()` → 新增 `institution` 参数
- Creates: `api.getInstitutions()`

- [ ] **Step 1: 修改 `SearchHit` 接口**

```typescript
export interface SearchHit {
  title: string;
  abstract: string | null;
  authors: string[] | null;
  author_affiliations: Array<{ name: string; institution: string | null }> | null;  // 新增
  year: number | null;
  // ... 其余不变 ...
}
```

- [ ] **Step 2: 修改 `search()` 参数类型**

```typescript
  search: (params: {
    query?: string;
    natural_query?: string;
    sources: string[];
    max_results: number;
    sort_by?: string;
    sort_order?: string;
    author?: string;
    journal?: string;
    preprint_sources?: string[];
    institution?: string;          // 新增
  }) => post<SearchResult>('/search', params),
```

- [ ] **Step 3: 同步修改 `searchStream()` 参数类型**

```typescript
  searchStream: async (
    params: {
      query?: string;
      natural_query?: string;
      sources: string[];
      max_results: number;
      sort_by?: string;
      sort_order?: string;
      author?: string;
      journal?: string;
      preprint_sources?: string[];
      institution?: string;          // 新增
    },
    onProgress: (current: number, total: number, source: string, sourceCount: number) => void,
  ): Promise<SearchResult> => {
```

- [ ] **Step 4: 新增 `InstitutionInfo` 类型和 `getInstitutions()` API**

```typescript
export interface InstitutionInfo {
  name: string;
  count: number;
}

export interface InstitutionListResponse {
  institutions: InstitutionInfo[];
  total_unique: number;
}
```

在 `api` 对象中新增：

```typescript
  getInstitutions: (limit = 20) =>
    get<InstitutionListResponse>(`/institutions?limit=${limit}`),
```

- [ ] **Step 5: 验证**

Run: `cd frontend && npx tsc --noEmit`

---

### Task 9: 前端 `SearchPage.tsx` — 机构输入框 UI

**Files:**
- Modify: `d:\ScholarFlow\frontend\src\pages\SearchPage.tsx`

**Interfaces:**
- 新增 state: `institution` (string)
- 新增 state: `institutionList` (InstitutionInfo[])
- 新增 UI: 机构输入框（combobox 模式）

- [ ] **Step 1: 新增 import**

```typescript
import { Search, Loader2, AlertCircle, Layers,
  BookOpen, Plus, ExternalLink, Sparkles, Tag, X, User, Building2,  // Building2 新增
} from 'lucide-react';
import { api, type SearchResult, type SearchHit, type InstitutionInfo } from '../lib/api';  // InstitutionInfo 新增
```

- [ ] **Step 2: 新增 state**

在 `SearchPage` 组件内，`journal` state 附近：

```typescript
  const [institution, setInstitution] = useState('');
  const [institutionList, setInstitutionList] = useState<InstitutionInfo[]>([]);
  const [showInstitutionDropdown, setShowInstitutionDropdown] = useState(false);
```

- [ ] **Step 3: 恢复 localStorage 中的 institution**

在 `useEffect` 恢复 localStorage 处新增：

```typescript
        if (state.institution) setInstitution(state.institution);
```

- [ ] **Step 4: 保存 localStorage 中的 institution**

在保存 localStorage 的 useEffect 中新增 `institution` 字段。

- [ ] **Step 5: 页面加载时获取机构列表**

新增 useEffect：

```typescript
  useEffect(() => {
    api.getInstitutions(20).then(data => {
      setInstitutionList(data.institutions);
    }).catch(() => {});
  }, []);
```

- [ ] **Step 6: 修改 `handleSearch()` 传递 `institution`**

在 `handleSearch()` 中，`params` 对象新增：

```typescript
          institution: institution || undefined,
```

两处（keyword 模式和 natural 模式）都要加。

- [ ] **Step 7: 新增 UI — 机构输入框**

在作者输入框（`<User className=...` 所在 div）之后，期刊筛选之前，新增机构输入框：

```tsx
      {/* 机构筛选 */}
      <div className="flex gap-2 mb-3">
        <div className="relative flex-1">
          <Building2 className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            value={institution}
            onChange={(e) => {
              setInstitution(e.target.value);
              setShowInstitutionDropdown(true);
            }}
            onFocus={() => setShowInstitutionDropdown(true)}
            onBlur={() => setTimeout(() => setShowInstitutionDropdown(false), 200)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="按机构筛选（可选），如 MIT、Stanford"
            className="w-full pl-10 pr-8 py-2 rounded-lg border border-gray-300 bg-white text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 transition-colors"
          />
          {institution && (
            <button
              onClick={() => setInstitution('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              title="清除机构筛选"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
          {/* 下拉预设列表 */}
          {showInstitutionDropdown && institutionList.length > 0 && (
            <div className="absolute z-20 left-0 right-0 top-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
              {institutionList
                .filter(i => !institution || i.name.toLowerCase().includes(institution.toLowerCase()))
                .map(i => (
                  <button
                    key={i.name}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      setInstitution(i.name);
                      setShowInstitutionDropdown(false);
                    }}
                    className="w-full text-left px-3 py-2 text-sm text-gray-700 hover:bg-indigo-50 hover:text-indigo-700 flex justify-between items-center"
                  >
                    <span>{i.name}</span>
                    <span className="text-xs text-gray-400">{i.count}篇</span>
                  </button>
                ))}
            </div>
          )}
        </div>
      </div>
```

- [ ] **Step 8: 修改搜索按钮 disabled 条件**

确保机构输入也可以触发搜索（当前 `!author.trim()` 逻辑在 keyword 模式下，需要改为 `!author.trim() && !institution.trim()` 或直接去掉该限制 —— 因为已经有 `query` 检查了）。

实际上现有逻辑 `(!hasKeyword && !author.trim())` 对于 natural 模式不适用。对于 keyword 模式：`(!query.trim() && !author.trim())` 应改为 `(!query.trim() && !author.trim() && !institution.trim())`。在 `handleSearch` 最前面已经有判断：

```typescript
    if ((!hasKeyword && !author.trim()) || sources.length === 0) return;
```

改为：

```typescript
    if ((!hasKeyword && !author.trim() && !institution.trim()) || sources.length === 0) return;
```

- [ ] **Step 9: 验证**

Run: `cd frontend && npx tsc --noEmit`

---

### Task 10: 端到端验证 + 更新 `dev_log.md`

- [ ] **Step 1: 启动后端验证语法**

```bash
cd D:\ScholarFlow && conda activate scholarflow && python -c "from app.main import app; print('Backend OK')"
```

- [ ] **Step 2: 前端构建**

```bash
cd D:\ScholarFlow\frontend && npm run build
```

- [ ] **Step 3: 更新 `dev_log.md`**

在 `dev_log.md` 的开发时间线区域新增：

```
代码生成(app/harvest, app/services, app/main.py, frontend): 新增机构筛选功能。author_utils.py 向后兼容解析；OpenAlex/PubMed 客户端解析机构并支持 institution 过滤；SearchHit/PaperMetadata 扩展 author_affiliations；新增 GET /institutions 端点返回本地库机构排名；前端新增机构输入框+预设下拉列表
```
