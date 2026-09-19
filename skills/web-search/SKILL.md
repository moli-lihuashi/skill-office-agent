---
name: web-search
description: 查询网络公开信息（标题/摘要），失败时自动降级到本地知识库。Use when 用户提到"搜索一下"、"查查网上"、"最新消息"、"web search"、"调研某主题"。不要用于纯本地文件查找。
keywords: [搜索一下, 查一下, 网上查, 网络信息, web search, 搜索引擎, 最新, 调研, 查询资料, 查资料]
entry: scripts/run.py
timeout: 15
retries: 1
tools: [http_get, search_web, search_knowledge_base]
fallback: knowledge_base
tags: [office, web]
---

# 网络信息查询

## Purpose
针对用户话题获取公开网络摘要；在超时、无网、接口失败时，无缝切换到本地知识库，保证 Agent 流水线不中断。

## Instructions
1. 参数：
   - `query`：检索词（必填）
   - `max_results`：默认 5
   - `timeout`：单次请求秒数（默认 10，受 Agent 容错层覆盖）
   - `prefer_local`：强制本地库（调试用）
2. 优先调用工具 `search_web`（DuckDuckGo HTML / 可配置引擎）。
3. 若返回空列表或异常：
   - 标记 `degraded=true`
   - 调用 `search_knowledge_base(query)` 查 `knowledge/office_kb.json`
   - 输出 `fallback.source=knowledge_base`
4. 输出 JSON：
   ```json
   {
     "skill": "web-search",
     "ok": true,
     "degraded": false,
     "query": "...",
     "results": [{"title":"...","url":"...","snippet":"..."}],
     "fallback": null,
     "warnings": []
   }
   ```
5. 绝不因网络失败让整条 Agent 任务中断——始终返回结构化结果。

## Multi-skill hooks
- `results` 可直接进入 `report-gen.context`。
- 串联示例：「查一下远程办公趋势并写成报告」→ web-search → report-gen。

## Examples
User: 搜索 Python 3.12 新特性
→ search_web(query="Python 3.12 new features")

## Troubleshooting
| 错误 | 原因 | 处理 |
|------|------|------|
| timeout | 网络慢/被墙 | 重试后降级 KB |
| HTTP 403 | 引擎拒绝 | 换 User-Agent 或换引擎 |
| 结果噪音大 | 查询过短 | 自动补限定词 "资料 OR 指南" |
