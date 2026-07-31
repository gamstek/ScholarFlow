# dev_log 写入示例

## 示例 1：需求分析

```
### 2026-07-23
需求分析(app/agent/name_utils, app/harvest/harvester): 作者/机构本地精确匹配方案设计

- 问题：中文作者名经 pypinyin 转拼音后，部分 API（PubMed、Nature 等）未使用 name_utils 转换，导致匹配失败
- 方案：设计「API 层粗筛 + 本地精确比对」双层架构
- 原因：外部 API 对中文名支持不一致，需在本地做二次过滤保证召回率
- 结果：name_utils 新增 match_author()/match_institution()，harvester 新增 _filter_by_author()/_filter_by_institution()
```

## 示例 2：代码生成

```
### 2026-07-23
代码生成(frontend, app/api): 批量入库/处理 API + 前端轮询优化

- 新增 POST /papers/import-batch 和 POST /papers/process-batch 端点
- 前端新增 importPapersBatch() / processPapersBatch() API 封装
- 结果：批量操作从 N 次请求降为 1 次，前端轮询从多定时器竞争改为全局单一 useRef
```

## 示例 3：用户推翻方案

```
### 2026-07-23
重构(start.bat, .env.example): 安全性加固与跨机器移植适配

- 原方案：start.bat 中包含硬编码密码，.env.example 含默认凭据
- 用户意见：移除所有硬编码密码，改为占位符，适配不同机器的端口和路径
- 最终采纳：start.bat 改为读取 .env 变量，.env.example 仅保留占位值
```
