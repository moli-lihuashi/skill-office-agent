---
name: email-draft
description: 根据要点或上游结果起草办公邮件/通知正文。Use when 用户提到"写邮件"、"起草邮件"、"邮件模板"、"通知草稿"、"email draft"、"发给同事的信"。不要用于完整长报告（那是 report-gen）。
keywords: [写邮件, 起草邮件, 邮件草稿, 邮件模板, 发邮件, email, draft, 通知, 写信, 邮件正文]
entry: scripts/run.py
timeout: 30
retries: 2
tools: [read_template, write_file]
fallback: template_only
tags: [office, communication]
---

# 邮件 / 通知草稿生成

## Purpose
生成结构清晰的中文办公邮件草稿：称呼、背景、要点、行动项、落款；可引用 report-gen 路径或 table-stats 关键数字。

## Instructions
1. 参数：
   - `to`：收件人（默认「同事」）
   - `subject`：主题
   - `points`：要点列表或字符串
   - `context`：上游技能结果（report / stats / search）
   - `tone`：`formal|brief|friendly`，默认 `formal`
   - `output_dir`：默认 `data/workspace`
2. 读取 `templates/email_template.md`；缺失则用内置模板。
3. 若 context 含 table-stats：自动插入「关键数据」小节。
4. 若 context 含 report-gen：在正文中附上报告路径。
5. 输出邮件全文并保存 `data/workspace/email_<ts>.txt`，返回 `output_path`。

## Multi-skill hooks
- 常见串联：table-stats / report-gen → email-draft。

## Examples
User: 给项目组写封邮件，说明本周销售数据
→ context=table-stats, to=项目组, subject=本周销售数据同步

## Troubleshooting
| 错误 | 原因 | 处理 |
|------|------|------|
| points 为空 | 用户未给要点 | 从 context 自动提炼 3 条 |
| 主题过长 | 未截断 | 截到 40 字加「…」 |
