---
name: report-gen
description: 将查询结果、表格统计与要点汇总成结构化办公报告（Markdown/文本）。Use when 用户提到"写报告"、"生成总结"、"汇总成文档"、"report"、"根据数据写说明"。不要用于单纯检索文件或只跑数字。
keywords: [写报告, 生成报告, 报告, 总结, 汇总成文档, report, summary, 生成总结, 报告生成, 分析报告]
entry: scripts/run.py
timeout: 40
retries: 2
tools: [read_template, write_file, format_report]
fallback: template_only
tags: [office, document]
---

# 报告生成

## Purpose
把上游技能产出（搜索结果 / 统计结果 / 网络摘要）组装为可直接使用的 Markdown 报告，并落盘到 `data/workspace`。

## Instructions
1. 参数：
   - `title`：报告标题（默认「办公 Agent 自动生成报告」）
   - `sections`：列表，每项 `{heading, content}` 或直接字符串
   - `context`：上游 JSON（`file-search` / `table-stats` / `web-search` 结果）
   - `output_dir`：默认 `data/workspace`
   - `format`：`md`（默认）或 `txt`
2. 读取 `templates/report_template.md`，填充标题、生成时间、来源、正文。
3. 若 context 含 table_stats：自动生成「数据概览」「关键指标」「分组结果」小节。
4. 若 context 含 search files：生成「相关文件」清单。
5. 若 context 含 web/search：生成「外部信息摘要」。
6. 写入 `data/workspace/report_<timestamp>.md`，返回绝对路径。
7. 模板缺失时：用内置 fallback 模板生成，不要失败。

## Multi-skill hooks
- 典型串联：web-search 或 file-search + table-stats → report-gen。
- 下游 `email-draft` 可读取本技能输出的 `output_path`。

## Examples
User: 根据刚才的统计写一份周报
→ context=table-stats 结果，title=销售数据周报

## Troubleshooting
| 错误 | 原因 | 处理 |
|------|------|------|
| 模板不存在 | templates 被删 | 使用内置模板 |
| 内容过空 | context 未传递 | 提示需要先搜索/统计 |
| 路径权限 | 目录只读 | 改写到 %TEMP% 并 warning |
