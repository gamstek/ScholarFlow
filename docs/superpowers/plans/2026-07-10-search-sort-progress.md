# 检索结果排序 + 检索进度显示 实施方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为文献检索增加按时间/引用量排序功能，以及检索过程实时进度显示。

**Architecture:** 排序采用"服务端首次排序 + 客户端即时重排"双模式，避免频繁请求；进度采用 SSE（Server-Sent Events）流式推送，harvester 逐数据源 yield 进度事件，前端通过 EventSource 实时渲染进度条。

**Tech Stack:** Python/FastAPI (SSE StreamingResponse), TypeScript/React (EventSource), Europe PMC API (`citedByCount`), Semantic Scholar API (`citationCount`)

**数据源覆盖：** arXiv（预印本）按用户要求排除。其余 5 个源均支持引用计数——Europe PMC / Nature / Science / Cell 四者均通过 Europe PMC 底层 API 获取 `citedByCount`；Semantic Scholar 通过自有 API 获取 `citationCount`。

## Global Constraints

- 保持项目领域中性（domain-agnostic），不引入特定学科假设
- 前端视觉风格保持现代科技感（indigo 色系 + 圆角卡片）
- 变更后需同步更新 `dev_log.md`
- 保持 `/search` 旧接口兼容，新功能走 `/search/stream`

---

## 文件结构

| 文件 | 职责 | 变更类型 |
|------|------|----------|
| `app/harvest/literature/europe_pmc_client.py` | `PaperMetadata` 增加 `citation_count`；新增 `parse_citation_count()` 共享解析函数；`EuropePmcClient` 使用之 | 修改 |
| `app/harvest/literature/nature_client.py` | `_parse_result_item` 中解析 `citedByCount` 并传入 `citation_count` | 修改 |
| `app/harvest/literature/science_client.py` | `_parse_result_item` 中解析 `citedByCount` 并传入 `citation_count` | 修改 |
| `app/harvest/literature/cell_client.py` | `_parse_result_item` 中解析 `citedByCount` 并传入 `citation_count` | 修改 |
| `app/harvest/literature/semantic_scholar_client.py` | 请求字段加 `citationCount`；解析并填入 `citation_count` | 修改 |
| `app/harvest/harvester.py` | `SearchHit` 加 `citation_count`；`search_only` 支持排序参数 + 进度回调；`search_only_stream` 新方法 | 修改 |
| `app/services/pipeline_service.py` | 新增 `search_papers_stream_service`；透传排序/进度参数 | 修改 |
| `app/main.py` | `SearchRequest` 加 `sort_by`/`sort_order`；新增 `POST /search/stream` SSE 端点 | 修改 |
| `app/storage/models.py` | `Paper` 模型加 `citation_count` 列（可选，入库时保存） | 修改 |
| `frontend/src/lib/api.ts` | `SearchHit` 加 `citation_count`；新增 `searchStream` 函数 | 修改 |
| `frontend/src/pages/SearchPage.tsx` | 排序下拉控件 + 进度条 UI + 客户端重排逻辑 | 修改 |

---

## Task 1: PaperMetadata 增加 citation_count + 共享解析函数

**涉及文件:** `app/harvest/literature/europe_pmc_client.py`

- [ ] 在 `PaperMetadata` dataclass 中新增字段 `citation_count: Optional[int] = None`（约第 53 行，`is_open_access` 之后）
- [ ] 新增 `parse_citation_count()` 共享函数（放在 `parse_open_access` 等函数附近）：

```python
def parse_citation_count(item: dict[str, Any]) -> Optional[int]:
    """
    解析引用计数。

    Europe PMC 的 resultType=core 返回 citedByCount 字段。
    其他经过 Europe PMC 的源（Nature/Science/Cell）也使用此函数。
    """
    value = item.get("citedByCount")
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
```

- [ ] 在 `EuropePmcClient._parse_result_item()` 中（约第 308 行 `return PaperMetadata(...)` 之前）：
  ```python
  citation_count = parse_citation_count(item)
  ```
  并在 `return PaperMetadata(...)` 中传入 `citation_count=citation_count`

**验证:** 启动后端，用 Europe PMC 源检索，确认 `results[].citation_count` 有值。

---

## Task 1b: Nature / Science / Cell 客户端同步增加 citation_count

> **背景:** Nature、Science、Cell 三个客户端在底层均调用 Europe PMC API（仅追加 journal 过滤条件），各自有独立的 `_parse_result_item`。需要同步更新。

**涉及文件:**
- `app/harvest/literature/nature_client.py`（`_parse_result_item` 约第 326-375 行）
- `app/harvest/literature/science_client.py`（`_parse_result_item` 约第 235-284 行）
- `app/harvest/literature/cell_client.py`（`_parse_result_item` 约第 261-306 行）

每个文件做相同修改：

- [ ] 在 import 中追加 `parse_citation_count`：
  ```python
  from app.harvest.literature.europe_pmc_client import (
      ...,
      parse_citation_count,  # 新增
  )
  ```
- [ ] 在 `_parse_result_item` 的 `return PaperMetadata(...)` 之前加：
  ```python
  citation_count = parse_citation_count(item)
  ```
- [ ] 在 `PaperMetadata(...)` 构造中传入 `citation_count=citation_count`

**验证:** 分别用 Nature、Science、Cell 源检索，确认 `citation_count` 有值（热门论文应有三位数以上引用）。

---

## Task 2: Semantic Scholar 客户端增加 citationCount

**涉及文件:** `app/harvest/literature/semantic_scholar_client.py`

- [ ] 在 `FIELDS` 常量中追加 `citationCount`（约第 43 行，`"publicationDate",` 之后加 `"citationCount",`）
- [ ] 在 `_parse_result_item()` 中解析 `citationCount`（约第 295 行，`is_open_access` 计算之后）：

```python
# 引用计数
cited_raw = item.get("citationCount")
citation_count = None
if cited_raw is not None:
    try:
        citation_count = int(cited_raw)
    except (ValueError, TypeError):
        citation_count = None
```

- [ ] 在 `return PaperMetadata(...)` 中传入 `citation_count=citation_count`

**验证:** 调用 Semantic Scholar 源检索，确认 `citation_count` 字段有值。

---

## Task 3: SearchHit 增加 citation_count

**涉及文件:** `app/harvest/harvester.py`

- [ ] 在 `SearchHit` dataclass 中新增字段 `citation_count: Optional[int] = None`（约第 82 行，`is_open_access` 之后）
- [ ] 在 `search_only()` 构造 `SearchHit` 处传入 `citation_count=paper.citation_count`（约第 269 行附近，`SearchHit(...)` 调用中）

**验证:** 类型检查无报错。

---

## Task 4: search_only 增加排序逻辑 + 进度回调

**涉及文件:** `app/harvest/harvester.py`

- [ ] `search_only()` 方法签名增加参数：
  ```python
  sort_by: str = "relevance",   # "relevance" | "year" | "citations"
  sort_order: str = "desc",     # "asc" | "desc"
  progress_callback: Optional[Callable[[int, int, str], None]] = None,
  ```
  （在第 198 行方法签名处修改）

- [ ] 在多源采集循环中（约第 218-233 行），每完成一个 source 后调用 `progress_callback`：
  ```python
  for idx, source in enumerate(sources):
      try:
          papers = self._search_one_source(...)
          all_papers.extend(papers)
          retrieved_count += len(papers)
      except Exception as exc:
          errors.append(...)
      finally:
          if progress_callback:
              # 计算总预期数：sources * max_results
              total_expected = len(sources) * max_results
              progress_callback(retrieved_count, total_expected, source)
  ```

- [ ] 在评分/去重之后（约第 269 行 `scored_papers.sort(...)` 之后），增加 sort_by 排序：
  ```python
  # 先按 domain_score 排（基础排序），再按用户选择重排
  reverse = (sort_order == "desc")
  if sort_by == "year":
      scored_papers.sort(key=lambda x: x[1].domain_score, reverse=True)  # 保留相关性兜底
      scored_papers.sort(key=lambda x: (x[0].year is not None, x[0].year or 0), reverse=reverse)
  elif sort_by == "citations":
      scored_papers.sort(key=lambda x: x[1].domain_score, reverse=True)
      scored_papers.sort(key=lambda x: (x[0].citation_count is not None, x[0].citation_count or 0), reverse=reverse)
  else:  # relevance
      scored_papers.sort(key=lambda x: x[1].domain_score, reverse=reverse)
  ```

  > **排序策略说明:** 采用稳定排序（Python sort 是稳定的），先按相关性排作为二级排序，再按用户选择的一级字段排。有值的排前面（`is not None` 为 True），无值的沉底。

- [ ] `SearchReport` dataclass 增加 `sort_by` 和 `sort_order` 字段（可选，用于前端回显当前排序状态）

- [ ] `search_report_to_dict()` 中透传 `sort_by` / `sort_order`

**验证:** 单元测试确认三种排序模式分别按预期字段排序，null 值正确沉底。

---

## Task 5: search_only_stream — 流式检索方法

**涉及文件:** `app/harvest/harvester.py`

- [ ] 新增 `search_only_stream()` 异步生成器方法。与 `search_only` 逻辑相同，但：
  - 通过 `progress_callback` yield SSE 格式的 progress 事件
  - 最后 yield 完整结果
  - 签名与 `search_only` 一致，额外加 `sort_by`/`sort_order`

```python
async def search_only_stream(
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
) -> AsyncGenerator[str, None]:
    """流式检索：逐源推送进度，最后返回完整结果。"""
    import json as _json

    total_expected = (len(sources) if sources else 1) * max_results
    current = 0

    def on_progress(retrieved: int, _total: int, source: str):
        nonlocal current
        current = retrieved
        yield f"data: {_json.dumps({'type': 'progress', 'current': current, 'total': total_expected, 'source': source})}\n\n"

    # ... 同 search_only 逻辑，但改为 async generator
```

> ⚠️ **实现注意:** 由于 harvester 的 `_search_one_source` 是同步的，需要在线程池中执行以避免阻塞 event loop。可用 `asyncio.to_thread` 或 `run_in_executor`。

**验证:** 用 curl 请求 `/search/stream`，观察 SSE 事件流是否逐条推送进度，最后推送完整 JSON 结果。

---

## Task 6: pipeline_service 增加流式检索服务函数

**涉及文件:** `app/services/pipeline_service.py`

- [ ] 新增 `search_papers_stream_service()` 函数，包装 `harvester.search_only_stream()`：

```python
from typing import AsyncGenerator

async def search_papers_stream_service(
    query: str,
    sources: list[str] | None = None,
    max_results: int = 20,
    enhance_query: bool = True,
    keywords: list[str] | None = None,
    domain: str | None = None,
    sort_by: str = "relevance",
    sort_order: str = "desc",
) -> AsyncGenerator[str, None]:
    harvester = LiteratureHarvester()
    async for event in harvester.search_only_stream(
        query=query,
        sources=sources,
        max_results=max_results,
        enhance_query=enhance_query,
        keywords=keywords,
        domain=domain,
        sort_by=sort_by,
        sort_order=sort_order,
    ):
        yield event
```

**验证:** 函数签名无报错，async generator 可正常 `async for` 迭代。

---

## Task 7: 后端 SearchRequest 增加排序参数 + 新增 /search/stream 端点

**涉及文件:** `app/main.py`

- [ ] 在 `SearchRequest` 中新增两个字段（约第 778 行 `enhance_query` 之后）：

```python
sort_by: str = Field(
    "relevance",
    description="排序方式：relevance（相关度）/ year（年份）/ citations（引用量）",
)
sort_order: str = Field(
    "desc",
    description="排序顺序：asc（升序）/ desc（降序）",
)
```

- [ ] 修改现有 `POST /search` 端点，透传 `sort_by`/`sort_order` 到 `search_papers_service()`：

```python
result = await search_papers_service(
    query=query,
    sources=request.sources,
    max_results=request.max_results,
    enhance_query=request.enhance_query,
    keywords=keywords,
    domain=domain,
    sort_by=request.sort_by,       # 新增
    sort_order=request.sort_order,  # 新增
)
```

- [ ] 新增 `POST /search/stream` SSE 端点：

```python
from fastapi.responses import StreamingResponse

@app.post("/search/stream")
async def search_stream(request: SearchRequest):
    """流式文献检索：通过 SSE 推送进度和结果。"""
    # 自然语言提取逻辑同 /search
    query = request.query.strip()
    keywords = None
    domain = None
    if request.natural_query and request.natural_query.strip():
        from app.agent.keyword_extractor import extract_keywords
        extraction = extract_keywords(request.natural_query)
        keywords = extraction.keywords
        domain = extraction.domain
        query = " ".join(keywords) if keywords else request.natural_query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="必须提供 query 或 natural_query。")

    async def event_stream():
        async for event in search_papers_stream_service(
            query=query,
            sources=request.sources,
            max_results=request.max_results,
            enhance_query=request.enhance_query,
            keywords=keywords,
            domain=domain,
            sort_by=request.sort_by,
            sort_order=request.sort_order,
        ):
            yield event

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )
```

**验证:** 启动后端，用 curl 测试两个端点均正常返回。

---

## Task 8: Paper 模型增加 citation_count（可选入库存储）

**涉及文件:** `app/storage/models.py`

- [ ] 在 `Paper` 模型中新增列（约第 120 行，`is_open_access` 之后）：

```python
citation_count = Column(Integer, nullable=True)
```

- [ ] 在入库逻辑中（`harvester._do_crawl` 的 paper 保存处）传入 `citation_count`

**验证:** 重启后端，检查数据库表结构已包含 `citation_count` 列。

> ⚠️ **注意:** 本字段为可选优化。排序功能本身不依赖入库存储——检索结果直接从 API 返回的引用计数排序。入库存储仅让已在库的论文也能按引用量浏览。

---

## Task 9: 前端 API 层增加 citation_count 和流式检索

**涉及文件:** `frontend/src/lib/api.ts`

- [ ] `SearchHit` interface 增加 `citation_count: number | null`（约第 64 行）
- [ ] `SearchResult` interface 增加 `sort_by?: string` 和 `sort_order?: string`（约第 80 行）
- [ ] `api.search()` 参数类型增加 `sort_by?: string` 和 `sort_order?: string`
- [ ] 新增 `api.searchStream()` 函数：

```typescript
searchStream: async (
  params: { ... },
  onProgress: (current: number, total: number, source: string) => void,
): Promise<SearchResult> => {
  const res = await fetch('/search/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6));
        if (data.type === 'progress') {
          onProgress(data.current, data.total, data.source);
        } else if (data.type === 'result') {
          return data as SearchResult;
        }
      }
    }
  }
  throw new Error('SSE stream ended without result');
},
```

**验证:** TypeScript 编译无报错。

---

## Task 10: SearchPage 增加排序控件 + 进度条 UI + 客户端重排

**涉及文件:** `frontend/src/pages/SearchPage.tsx`

### 10a. 新增状态变量

- [ ] 在组件顶部状态区（约第 27 行附近）新增：

```typescript
const [sortBy, setSortBy] = useState<string>('relevance');
const [sortOrder, setSortOrder] = useState<string>('desc');
const [searchProgress, setSearchProgress] = useState<{
  current: number; total: number; source: string;
} | null>(null);
```

### 10b. 排序 UI 控件

- [ ] 在统计卡片行（`<div className="grid grid-cols-3 gap-3 mb-6">`）上方新增排序栏：

```tsx
{result && !loading && (
  <div className="flex items-center gap-3 mb-4">
    <span className="text-xs text-gray-500">排序：</span>
    {[
      { value: 'relevance', label: '相关度' },
      { value: 'year', label: '发表时间' },
      { value: 'citations', label: '引用量' },
    ].map((opt) => (
      <button
        key={opt.value}
        onClick={() => {
          if (sortBy === opt.value) {
            setSortOrder((o) => (o === 'desc' ? 'asc' : 'desc'));
          } else {
            setSortBy(opt.value);
            setSortOrder('desc');
          }
        }}
        className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors border ${
          sortBy === opt.value
            ? 'bg-indigo-600 text-white border-indigo-600'
            : 'bg-white text-gray-600 border-gray-200 hover:border-indigo-300'
        }`}
      >
        {opt.label}
        {sortBy === opt.value && (
          <span className="ml-1">{sortOrder === 'desc' ? '↓' : '↑'}</span>
        )}
      </button>
    ))}
  </div>
)}
```

### 10c. 客户端排序逻辑

- [ ] 在渲染结果列表前（约第 237 行 `result.results.map(...)` 处），用 `useMemo` 计算排序后的结果：

```typescript
const sortedResults = useMemo(() => {
  if (!result) return [];
  const list = [...result.results];
  const desc = sortOrder === 'desc';
  if (sortBy === 'year') {
    list.sort((a, b) => {
      const ay = a.year ?? 0; const by = b.year ?? 0;
      const aHas = a.year != null; const bHas = b.year != null;
      if (aHas !== bHas) return aHas ? -1 : 1;
      return desc ? by - ay : ay - by;
    });
  } else if (sortBy === 'citations') {
    list.sort((a, b) => {
      const ac = a.citation_count ?? 0; const bc = b.citation_count ?? 0;
      const aHas = a.citation_count != null; const bHas = b.citation_count != null;
      if (aHas !== bHas) return aHas ? -1 : 1;
      return desc ? bc - ac : ac - bc;
    });
  } else {
    list.sort((a, b) => desc ? b.domain_score - a.domain_score : a.domain_score - b.domain_score);
  }
  return list;
}, [result, sortBy, sortOrder]);
```

- [ ] 将 `result.results.map(...)` 替换为 `sortedResults.map(...)`

### 10d. 进度条 UI

- [ ] 在检索按钮下方、结果区上方，新增进度条组件（条件渲染，`searchProgress != null` 时显示）：

```tsx
{searchProgress && (
  <div className="mb-4 animate-fade-in">
    <div className="flex items-center justify-between mb-1.5">
      <span className="text-xs text-gray-500">
        检索进度：{searchProgress.current} / {searchProgress.total}
      </span>
      <span className="text-xs text-gray-400">
        当前数据源：{searchProgress.source}
      </span>
    </div>
    <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
      <div
        className="h-full bg-indigo-500 rounded-full transition-all duration-500 ease-out"
        style={{ width: `${(searchProgress.current / searchProgress.total) * 100}%` }}
      />
    </div>
  </div>
)}
```

### 10e. 切换 handleSearch 使用流式接口

- [ ] 修改 `handleSearch`（约第 54 行），将 `api.search()` 替换为 `api.searchStream()`：

```typescript
const handleSearch = async () => {
  // ... 前置校验不变 ...

  setLoading(true);
  setError('');
  setResult(null);
  setSearchProgress(null);

  try {
    const params = {
      ...(mode === 'natural'
        ? { natural_query: naturalQuery, sources, max_results: maxResults }
        : { query, sources, max_results: maxResults }),
      sort_by: sortBy,
      sort_order: sortOrder,
    };

    const data = await api.searchStream(params, (current, total, source) => {
      setSearchProgress({ current, total, source });
    });
    setResult(data);
    setSearchProgress(null);
  } catch (err) {
    setError(err instanceof Error ? err.message : String(err));
    setSearchProgress(null);
  } finally {
    setLoading(false);
  }
};
```

### 10f. PaperCard 显示引用量

- [ ] 在 `PaperCard` 组件的元信息行（约第 293 行），年份旁边增加引用量显示：

```tsx
{hit.citation_count != null && (
  <span className="text-[10px] text-gray-400">
    · 被引 {hit.citation_count} 次
  </span>
)}
```

**验证:** 
1. 选择多个数据源 + 较大 maxResults，点击检索，观察进度条推进和"当前数据源"标签
2. 检索完成后点击排序按钮切换"相关度/发表时间/引用量"，观察列表即时重排
3. 切换升序/降序，确认箭头方向正确
4. PaperCard 上确认有引用次数的论文显示"被引 X 次"

---

## Task 11: 同步开发日志

**涉及文件:** `dev_log.md`

- [ ] 在开发时间线中追加：
  ```
  代码生成(harvester+frontend): 检索结果增加按时间/引用量排序 + SSE 流式检索进度显示
  ```

---

## 依赖关系

```
Task 1 (PaperMetadata + parse fn) ──→ Task 1b (Nature/Science/Cell 同步)
Task 2 (Semantic Scholar)           │
        │                            │
        ▼                            ▼
              Task 3 (SearchHit) ──→ Task 4,5 (排序/流式)
                                            │
                                            ▼
                                      Task 6,7 (service + API)
                                            │
                                            ▼
                                 Task 8 (模型, 可选)   Task 9 (前端 API)
                                            │               │
                                            ▼               ▼
                                      Task 10 (前端 UI) ←──┘
                                            │
                                            ▼
                                      Task 11 (日志)
```

---

## 风险与注意事项

1. **Europe PMC `citedByCount` 延迟:** 该字段反映 Europe PMC 内部索引的引用次数，与 Google Scholar 等可能有差异，但对趋势排序足够。Nature/Science/Cell 三个源经同一 API，数据质量一致。
2. **Semantic Scholar `citationCount` 覆盖面:** S2 的引用计数来自其自建索引，对计算机/生物医学领域覆盖较好，其他领域可能偏少。
3. **arXiv（预印本）排除:** 按用户要求不处理 arXiv 的引用数据。该源论文的 `citation_count` 为 null，按引用量排序时沉底。
4. **SSE 与代理兼容性:** 如果前端部署在 nginx 后，需确保 `proxy_buffering off;` 且 `X-Accel-Buffering: no` 头已设置。
5. **流式接口的超时:** 检索 3 个源 × 100 篇可能耗时 10-30 秒，SSE 连接需保持足够长的超时时间。
6. **向后兼容:** 保留原 `/search` 端点不变，新增 `/search/stream`。前端默认使用流式接口，原接口作为降级方案。
