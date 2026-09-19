#!/usr/bin/env python3
"""report-gen skill entry: assemble markdown office report from context."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.document import format_report, write_text_file  # noqa: E402
from tools.llm_text import polish_report, resolve_llm_config  # noqa: E402


BUILTIN_TEMPLATE = """# {title}

- 生成时间：{generated_at}
- 生成方式：Skill Office Agent / report-gen

## 摘要
{summary}

{body}

---
*本报告由技能化办公 Agent 自动生成。*
"""


def _read_template() -> str:
    tpl = ROOT / "templates" / "report_template.md"
    if tpl.exists():
        return tpl.read_text(encoding="utf-8")
    return BUILTIN_TEMPLATE


def _render_context(context: dict | None) -> tuple[str, list[str]]:
    """Return (body_markdown, source_tags)."""
    if not context:
        return "暂无上游数据，请先执行检索或统计技能。", []
    tags = []
    parts: list[str] = []

    # support list of chained results
    items = context if isinstance(context, list) else [context]
    # if single dict of form {results: [...]}
    if isinstance(context, dict) and "results" in context:
        items = context.get("results") or [context]

    for item in items:
        if not isinstance(item, dict):
            continue
        skill = item.get("skill") or item.get("source") or "unknown"
        tags.append(skill)
        ok = item.get("ok", True)
        status = "成功" if ok else "失败"
        parts.append(f"### 来源技能：`{skill}`（{status}）")

        if skill == "file-search" or "files" in item:
            files = item.get("files") or []
            parts.append(f"- 检索根目录：`{item.get('root', '-')}`")
            parts.append(f"- 命中数量：{item.get('count', len(files))}")
            if files:
                parts.append("- 文件列表：")
                for f in files[:10]:
                    parts.append(f"  - `{f.get('path', f.get('name', '?'))}`")
            if item.get("fallback"):
                parts.append("- 本地检索无结果，已使用知识库提示兜底。")

        if skill == "table-stats" or "numeric_describe" in item:
            parts.append(f"- 数据文件：`{item.get('path', '-')}`")
            parts.append(f"- 规模：{item.get('rows', '-')} 行 × {item.get('cols', '-')} 列")
            desc = item.get("numeric_describe") or {}
            if desc:
                parts.append("- 数值列摘要：")
                for col, stats in list(desc.items())[:6]:
                    if isinstance(stats, dict):
                        parts.append(
                            f"  - **{col}**: mean={stats.get('mean')}, "
                            f"min={stats.get('min')}, max={stats.get('max')}"
                        )
            gr = item.get("group_result")
            if gr and isinstance(gr, dict):
                parts.append(f"- 分组聚合：`{gr.get('group_by')}` / `{gr.get('agg_func')}`")
                for row in (gr.get("values") or [])[:15]:
                    parts.append(f"  - {row.get('key')}: {row.get('value')}")

        if skill in {"web-search", "local-kb"} or "results" in item and "files" not in item:
            results = item.get("results") or item.get("items") or []
            parts.append("- 信息条目：")
            for r in results[:8]:
                if isinstance(r, dict):
                    parts.append(f"  - **{r.get('title', '条目')}**：{r.get('snippet') or r.get('summary') or r.get('url') or ''}")
                else:
                    parts.append(f"  - {r}")

        if item.get("error"):
            parts.append(f"- 错误信息：{item['error']}")
        parts.append("")

    body = "\n".join(parts).strip()
    summary = f"报告覆盖 {len(tags)} 个技能产出：" + "、".join(tags) if tags else "无上游技能产出"
    return body, summary if False else (body, tags)  # keep signature simple below


def run(params: dict) -> dict:
    title = str(params.get("title") or "办公 Agent 自动生成报告")
    context = params.get("context")
    output_dir = Path(params.get("output_dir") or (ROOT / "data" / "workspace"))
    fmt = str(params.get("format") or "md").lower().lstrip(".")
    extra_sections = params.get("sections") or []
    warnings: list[str] = []

    body_parts: list[str] = []
    tags: list[str] = []

    items = []
    if isinstance(context, list):
        items = context
    elif isinstance(context, dict):
        if "results" in context:
            items = context["results"]
        else:
            items = [context]

    for item in items:
        if not isinstance(item, dict):
            continue
        skill = item.get("skill") or item.get("source") or "unknown"
        tags.append(str(skill))
        ok = item.get("ok", True)
        body_parts.append(f"### 来源技能：`{skill}`（{'成功' if ok else '失败'}）")
        if skill == "file-search" or "files" in item:
            files = item.get("files") or []
            body_parts.append(f"- 检索根目录：`{item.get('root', '-')}`")
            body_parts.append(f"- 命中数量：{item.get('count', len(files))}")
            if files:
                body_parts.append("- 文件列表：")
                for f in files[:10]:
                    body_parts.append(f"  - `{f.get('path', f.get('name', '?'))}`")
        if skill == "table-stats" or "numeric_describe" in item:
            body_parts.append(f"- 数据文件：`{item.get('path', '-')}`")
            body_parts.append(f"- 规模：{item.get('rows', '-')} 行 × {item.get('cols', '-')} 列")
            desc = item.get("numeric_describe") or {}
            for col, stats in list(desc.items())[:6]:
                if isinstance(stats, dict):
                    body_parts.append(
                        f"  - **{col}**: mean={stats.get('mean')}, min={stats.get('min')}, max={stats.get('max')}"
                    )
            gr = item.get("group_result")
            if isinstance(gr, dict):
                body_parts.append(f"- 分组：`{gr.get('group_by')}` → `{gr.get('agg_col')}` ({gr.get('agg_func')})")
                for row in (gr.get("values") or [])[:15]:
                    body_parts.append(f"  - {row.get('key')}: {row.get('value')}")
        if skill in {"web-search", "local-kb"} or ("results" in item and "files" not in item):
            results = item.get("results") or item.get("items") or []
            for r in results[:8]:
                if isinstance(r, dict):
                    body_parts.append(
                        f"  - **{r.get('title', '条目')}**：{r.get('snippet') or r.get('summary') or r.get('url') or ''}"
                    )
        if item.get("error"):
            body_parts.append(f"- 错误信息：{item['error']}")
        if item.get("fallback"):
            body_parts.append("- 已触发本地兜底策略。")
        body_parts.append("")

    for sec in extra_sections:
        if isinstance(sec, dict):
            body_parts.append(f"### {sec.get('heading', '补充')}")
            body_parts.append(str(sec.get("content", "")))
        else:
            body_parts.append(str(sec))

    if not body_parts:
        body_parts.append("暂无上游数据，请先执行检索或统计技能。")

    summary = (
        f"报告覆盖 {len(tags)} 个技能产出：" + "、".join(tags)
        if tags
        else "本报告未绑定上游技能数据，为模板占位输出。"
    )

    template = _read_template()
    try:
        report_text = format_report(
            template,
            title=title,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            summary=summary,
            body="\n".join(body_parts).strip(),
        )
    except Exception as e:  # noqa: BLE001
        warnings.append(f"template fill failed: {e}; using builtin")
        report_text = BUILTIN_TEMPLATE.format(
            title=title,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            summary=summary,
            body="\n".join(body_parts).strip(),
        )

    llm_cfg = resolve_llm_config(params)
    llm_polish = {
        "enabled": bool(params.get("llm_polish", llm_cfg.get("polish", True))) and llm_cfg.get("base_url") and llm_cfg.get("model"),
        "used": False,
        "error": None,
    }
    if llm_polish["enabled"]:
        polished, err = polish_report(title, report_text, context if context is not None else body_parts, llm_cfg)
        if polished:
            report_text = polished
            llm_polish["used"] = True
        else:
            llm_polish["error"] = err
            warnings.append(f"llm polish failed, keep template: {err}")

    fname = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{fmt}"
    try:
        path = write_text_file(output_dir, fname, report_text)
        ok = True
        error = None
    except Exception as e:  # noqa: BLE001
        import tempfile
        path = write_text_file(Path(tempfile.gettempdir()), fname, report_text)
        warnings.append(f"workspace not writable, saved to {path}")
        ok = True
        error = None

    return {
        "skill": "report-gen",
        "ok": ok,
        "error": error,
        "title": title,
        "output_path": str(path),
        "format": fmt,
        "sources": tags,
        "preview": report_text[:800],
        "warnings": warnings,
        "llm_polish": llm_polish,
        "fallback": None,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    raw = sys.stdin.read().strip() if not sys.stdin.isatty() else ""
    if raw:
        params = json.loads(raw)
    else:
        params = {
            arg.split("=", 1)[0]: arg.split("=", 1)[1]
            for arg in sys.argv[1:]
            if "=" in arg
        }
    print(json.dumps(run(params), ensure_ascii=False, indent=2))
