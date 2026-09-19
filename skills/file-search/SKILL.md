---
name: file-search
description: 在本地目录中按文件名、扩展名、内容关键词检索文件。Use when 用户提到"找文件"、"搜索文档"、"查找 Excel"、"locate file"、"哪个文件里有"、文件名/路径检索。不要用于网络搜索或打开文件内容分析。
keywords: [找文件, 搜索文件, 查找文档, 文件检索, locate, find file, file search, 搜索目录, 找一下, 哪个文件, 文件名]
entry: scripts/run.py
timeout: 30
retries: 2
tools: [list_files, search_files, read_file_meta]
fallback: knowledge_base
tags: [office, filesystem]
---

# 本地文件检索

## Purpose
在用户指定（或默认工作区）目录中，按名称模式、扩展名、修改时间与内容关键词定位文件，返回结构化结果供后续技能（表格统计、报告生成）复用。

## Instructions
1. 解析参数：
   - `query`：文件名/关键词（必填）
   - `root`：搜索根目录（默认 `D:\skill-office-agent\data`，也允许用户给绝对路径）
   - `ext`：扩展名过滤，如 `xlsx,csv`
   - `limit`：最多返回条数（默认 20）
2. 调用 `search_files` 工具，优先匹配文件名，其次可选 `content` 搜索。
3. 输出 JSON：
   ```json
   {
     "skill": "file-search",
     "count": 2,
     "files": [{"path": "...", "name": "...", "ext": ".xlsx", "size": 1234, "mtime": "..."}],
     "root": "D:\\..."
   }
   ```
4. 若 0 结果：扩大 ext 范围再搜一次；仍为 0 则查本地知识库 `office_kb.json` 的 `file_hints` 给建议。

## Multi-skill hooks
- `outputs.files[0].path` 可作为 `table-stats` / `report-gen` 的输入。
- 触发串联示例：「找一下销售表并统计」→ file-search → table-stats。

## Examples
User: 帮我找 D:\skill-office-agent\data 下所有 csv
→ search_files(root=D:\skill-office-agent\data, query="*", ext="csv")
→ 返回文件列表

User: 哪个文件里有"季度销售"
→ search_files(query="季度销售", content=true)

## Troubleshooting
| 错误 | 原因 | 处理 |
|------|------|------|
| PermissionError | 无目录权限 | 跳过该目录并记入 warnings |
| 路径不存在 | root 错误 | 回退到默认 data 目录 |
| 结果过多 | query 过宽 | 使用 limit + 按 mtime 排序 |
