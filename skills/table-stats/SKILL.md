---
name: table-stats
description: 对 CSV/Excel 表格做描述性统计与分组汇总。Use when 用户提到"统计表格"、"算平均值"、"数据汇总"、"分析 Excel/CSV"、"summarize data"、"按某列分组"。不要用于生成长篇报告正文或写邮件。
keywords: [统计, 汇总, 平均, 分析表格, 表格数据, excel分析, csv分析, describe, summarize, groupby, 数据分析, 求和, 数据统计]
entry: scripts/run.py
timeout: 45
retries: 2
tools: [read_table, describe_table, group_by_table]
fallback: knowledge_base
tags: [office, data]
---

# 表格数据统计

## Purpose
读取本地 CSV/XLSX，输出列概览、数值描述统计，以及可选的分组聚合结果。

## Instructions
1. 参数：
   - `path`：表格文件路径（优先使用上游 `file-search` 的 `files[0].path`）
   - `group_by`：可选分组列
   - `agg_col`：可选聚合数值列
   - `agg_func`：`sum|mean|count|min|max`，默认 `sum`
   - `head`：预览行数，默认 5
2. 若缺 `path`：先调用 `search_files(root=data, query=*.csv|*.xlsx)` 取第一个命中。
3. 用 `tools.spreadsheet.load_table` 读取；生成：
   - `profile`: 列名、dtype、非空数、唯一值数
   - `numeric_describe`: count/mean/std/min/25%/50%/75%/max
   - `group_result`: 指定分组聚合（若提供 group_by）
4. 输出 JSON，键固定：`skill, ok, path, rows, cols, profile, numeric_describe, group_result, preview, warnings, fallback`。
5. 读表失败：尝试用 pandas 默认引擎/latin-1 重试；仍失败则查 KB `table_tips` 并降级返回错误说明。

## Multi-skill hooks
- 结果可直接喂给 `report-gen`（`context.table_stats`）。
- 串联示例：「找出销售表并统计各区域销售额」→ file-search + table-stats。

## Examples
User: 统计 D:\...\sales.csv 按 Region 的销售额
→ group_by=Region, agg_col=sales, agg_func=sum

## Troubleshooting
| 错误 | 原因 | 处理 |
|------|------|------|
| EmptyDataError | 空文件/错分隔符 | 自动 sniff sep 再读 |
| KeyError group_by | 列名不符 | fuzzy match 列名（忽略空格/大小写） |
| 文件被占用 | Excel 打开中 | 提示关闭文件或复制副本 |
