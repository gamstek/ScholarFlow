# 作者搜索 + 机构筛选 设计方案

> 版本: v1.0 | 日期: 2026-07-22 | 状态: 设计中

---

## 1. 需求概述

### 1.1 用户故事
- 作为研究者，我希望按作者名搜索文献，快速定位某位学者的工作
- 作为研究者，我希望按机构筛选，找到特定实验室/大学的研究成果
- 机构粒度需支持大学级（MIT）和实验室级（MIT CSAIL）
- 入库时需存储机构信息，为后续本地查询打基础
- 已知机构列表按本地库出现频率降序排列

### 1.2 当前状态

| 维度 | 现状 |
|---|---|
| 作者搜索 | 已有 `author` 参数，纯文本拼入检索式 |
| 机构搜索 | ❌ 完全不存在 |
| 作者数据存储 | `Paper.authors_json` = `list[str]`，无机构信息 |
| OpenAlex 数据 | `authorships[].institutions[]` 有完整机构数据，但被丢弃 |
| PubMed | 支持 `[AD]` affiliation 检索，但未利用 |
| 前端 UI | 仅有作者名输入框 |

---

## 2. 方案选择

### 方案 A（轻量级）：仅检索时过滤，不存储
- 改动 ~50 行，不修改数据模型
- ❌ 不支持 Europe PMC 等主流源
- ❌ 无法做本地机构查询

### 方案 B（推荐）✅：检索过滤 + 入库存储 + 向后兼容
- 扩展 `authors_json` 格式（向后兼容）
- 提取并存储机构数据
- 前端机构预设列表（按 local DB 频率排序）
- 改动 ~200 行，集中在 8 个文件

### 方案 C（重量级）：独立 authors/institutions 表
- ❌ 当前阶段过度设计，不符合项目定位

---

## 3. 详细设计

### 3.1 数据模型变更

**`authors_json` 格式升级（向后兼容）**：

```python
# 旧格式（继续支持）
["Geoffrey Hinton", "Yann LeCun"]

# 新格式
[
  {"name": "Geoffrey Hinton", "institution": "University of Toronto"},
  {"name": "Yann LeCun", "institution": "New York University"}
]
```

**兼容解析器**（新增 `app/harvest/literature/author_utils.py`）：

```python
def parse_authors_json(authors_json: str | None) -> list[dict]:
    """向后兼容解析 authors_json。旧格式为 list[str]，新格式为 list[dict]."""
    if not authors_json: return []
    data = json.loads(authors_json)
    result = []
    for item in data:
        if isinstance(item, str):
            result.append({"name": item, "institution": None})
        else:
            result.append(item)
    return result

def format_authors_json(authors: list[dict]) -> str:
    """将结构化作者列表序列化为 JSON 字符串。"""
    return json.dumps(authors, ensure_ascii=False)
```

### 3.2 `PaperMetadata` 扩展

```python
@dataclass
class PaperMetadata:
    # ... 现有字段 ...
    authors: Optional[list[str]] = None            # 已有（保持兼容）
    author_affiliations: Optional[list[dict]] = None  # 新增
```

### 3.3 `SearchHit` 扩展

```python
@dataclass
class SearchHit:
    # ... 现有字段 ...
    authors: Optional[list[str]] = None
    author_affiliations: Optional[list[dict]] = None  # 新增
```

### 3.4 各数据源支持矩阵

| 数据源 | 作者搜索 | 机构搜索 | 机构解析 | 备注 |
|---|---|---|---|---|
| Europe PMC | ✅ `AUTH:` | ❌ | ❌ | API 不返回机构 |
| PubMed | ✅ `[AU]` | ✅ `[AD]` | ✅ | XML 有 AffiliationInfo |
| OpenAlex | ✅ `author.search` | ✅ `institutions.id` | ✅ | `authorships[].institutions[]` |
| Semantic Scholar | ✅ 嵌入 query | ❌ | ❌ | |
| arXiv | ✅ `au:` | ❌ | ❌ | |
| Nature/Science/Cell | ✅ 嵌入 query | ❌ | ❌ | |

### 3.5 API 变更

**`POST /search` 请求体**：

```python
class SearchRequest(BaseModel):
    # ... 现有字段 ...
    author: Optional[str] = None
    institution: Optional[str] = None  # 新增
```

**`GET /papers` 新增机构过滤**：

```python
@app.get("/papers")
async def list_papers(
    # ... 现有参数 ...
    institution: Optional[str] = Query(None),  # 新增：本地库机构过滤
):
```

**新增 `GET /institutions` 端点**：

```python
@app.get("/institutions")
async def list_institutions() -> dict:
    """
    返回本地文献库中机构排名（按出现频率降序）。
    用于前端机构预设下拉列表。
    """
    # 从 papers.authors_json 中提取所有 institution，
    # 聚合计数，降序排列返回 top 20
```

### 3.6 前端 UI 设计

```
┌───────────────────────────────────────────────────┐
│  🔍 [关键词搜索...]                  [搜索]       │
│  👤 [按作者筛选，如 Geoffrey Hinton]    [×]       │
│  🏛️ [按机构筛选（可选），如 MIT]  ▼    [×]       │
│     ├─ MIT (15篇)                                │
│     ├─ Stanford University (12篇)                │
│     ├─ Harvard University (8篇)                  │
│     └─ 输入自定义机构...                          │
│  📰 [期刊筛选...]                        [×]      │
└───────────────────────────────────────────────────┘
```

- 机构输入框为 **datalist/combobox** 模式：可自由输入，也可从预设列表选择
- 预设列表从 `GET /institutions` 获取，按本地库频率降序
- 选中不支持机构筛选的源时，输入框变灰 + tooltip

### 3.7 涉及文件清单

```
后端（7 个文件）：
├── app/harvest/literature/author_utils.py        [新建] 兼容解析器
├── app/harvest/literature/europe_pmc_client.py   [修改] PaperMetadata 加字段
├── app/harvest/literature/openalex_client.py     [修改] 解析 institution + filter
├── app/harvest/literature/pubmed_client.py       [修改] [AD] 检索 + affiliation 解析
├── app/harvest/harvester.py                      [修改] SearchHit + 透传
├── app/services/pipeline_service.py              [修改] 参数透传
├── app/main.py                                   [修改] SearchRequest + /institutions

前端（2 个文件）：
├── frontend/src/lib/api.ts                       [修改] 类型 + 参数
└── frontend/src/pages/SearchPage.tsx             [修改] UI + 机构列表
```

---

## 4. 机构预设列表设计

### 4.1 数据来源
从本地 `papers` 表的 `authors_json` 字段提取所有 institution。

### 4.2 排序规则
按 institution 出现次数降序排列，取 Top 20。

### 4.3 API 设计

```
GET /institutions

Response:
{
  "institutions": [
    {"name": "MIT", "count": 15},
    {"name": "Stanford University", "count": 12},
    ...
  ],
  "total_unique": 85
}
```

### 4.4 实现方式
SQL 层面无法直接查询 JSON 数组内的字段（SQLite 无 jsonb），所以在 Python 层聚合：

```python
async def get_top_institutions(limit: int = 20) -> list[dict]:
    papers = await paper_repo.list_all_authors_json()
    counter: dict[str, int] = {}
    for paper in papers:
        authors = parse_authors_json(paper.get("authors_json"))
        for a in authors:
            inst = a.get("institution")
            if inst:
                counter[inst] = counter.get(inst, 0) + 1
    sorted_insts = sorted(counter.items(), key=lambda x: x[1], reverse=True)
    return [{"name": k, "count": v} for k, v in sorted_insts[:limit]]
```

---

## 5. 向后兼容性

| 场景 | 处理方式 |
|---|---|
| 旧数据 `authors_json = ["John"]`  | `parse_authors_json()` 自动转为 `[{name:"John", institution:null}]` |
| 旧 API 调用不传 `institution` | 默认 `None`，行为不变 |
| 前端旧 localStorage 缓存 | `institution` 字段不存在时默认 `""` |

---

## 6. 自审清单

- [x] 各数据源覆盖矩阵明确（哪些支持机构）
- [x] 向后兼容旧 `authors_json` 格式
- [x] 前端机构列表从本地 DB 聚合
- [x] 机构支持大学级 + 实验室级（自由文本输入）
- [x] 入库时同步存储机构信息
- [x] 不与现有 author/journal 筛选冲突
- [ ] 旧数据迁移方案（重建索引时自动补齐）
