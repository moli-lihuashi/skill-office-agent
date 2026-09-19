#!/usr/bin/env python3
"""email-draft skill entry: office email / notification draft."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.document import write_text_file  # noqa: E402
from tools.llm_text import polish_email, resolve_llm_config  # noqa: E402

BUILTIN = """收件人：{to}
主题：{subject}

{salutation}：

{opening}

{body}

{action}

{closing}

——
{signature}
"""


def _auto_points_from_context(context) -> list[str]:
    points: list[str] = []
    items = context if isinstance(context, list) else [context] if context else []
    if isinstance(context, dict) and "results" in context:
        items = context["results"]
    for item in items:
        if not isinstance(item, dict):
            continue
        skill = item.get("skill") or item.get("source")
        if skill == "table-stats" or "numeric_describe" in item:
            points.append(f"数据文件：{item.get('path', '-')}，规模 {item.get('rows','-')}×{item.get('cols','-')}")
            desc = item.get("numeric_describe") or {}
            for col, st in list(desc.items())[:3]:
                if isinstance(st, dict):
                    points.append(f"{col}：均值 {st.get('mean')}，范围 [{st.get('min')}, {st.get('max')}]")
            gr = item.get("group_result")
            if isinstance(gr, dict) and gr.get("values"):
                top = gr["values"][:3]
                pretty = "，".join(f"{r.get('key')}={r.get('value')}" for r in top)
                points.append(f"分组结果（{gr.get('group_by')}）：{pretty}")
        if skill == "report-gen" or "output_path" in item:
            points.append(f"详细报告见：{item.get('output_path')}")
        if skill == "file-search" or "files" in item:
            points.append(f"相关文件 {item.get('count', len(item.get('files') or []))} 个已定位")
        if skill == "web-search" or (item.get("results") and "files" not in item):
            for r in (item.get("results") or [])[:2]:
                if isinstance(r, dict):
                    points.append(f"参考：{r.get('title')} — {r.get('url') or r.get('snippet') or ''}")
    return points


def run(params: dict) -> dict:
    to = str(params.get("to") or "同事")
    subject = str(params.get("subject") or "工作同步")
    if len(subject) > 40:
        subject = subject[:39] + "…"
    points_raw = params.get("points") or []
    if isinstance(points_raw, str):
        points_raw = [p.strip() for p in points_raw.split(";") if p.strip()] or [points_raw]
    context = params.get("context")
    tone = str(params.get("tone") or "formal")
    output_dir = Path(params.get("output_dir") or (ROOT / "data" / "workspace"))
    warnings: list[str] = []

    points = list(points_raw)
    auto = _auto_points_from_context(context)
    if not points and auto:
        points = auto
        warnings.append("points empty; auto-derived from context")
    if not points:
        points = ["请补充本次沟通的具体事项。"]

    tone_map = {
        "formal": {"salutation": f"尊敬的{to}", "opening": "您好！", "closing": "如有疑问欢迎随时沟通。", "signature": "Skill Office Agent"},
        "brief": {"salutation": f"{to}", "opening": "你好，", "closing": "请查收。", "signature": "Agent"},
        "friendly": {"salutation": f"Hi {to}", "opening": "你好呀～", "closing": "有问题直接回我哈。", "signature": "Office Agent"},
    }
    tone_cfg = tone_map.get(tone, tone_map["formal"])

    body_lines = ["现将相关信息同步如下：", ""]
    for i, p in enumerate(points, 1):
        body_lines.append(f"{i}. {p}")
    action = "行动项：请相关同学在两个工作日内确认反馈。"

    tpl_path = ROOT / "templates" / "email_template.md"
    if tpl_path.exists():
        try:
            raw_tpl = tpl_path.read_text(encoding="utf-8")
            email_text = raw_tpl.format(
                to=to,
                subject=subject,
                salutation=tone_cfg["salutation"],
                opening=tone_cfg["opening"],
                body="\n".join(body_lines),
                action=action,
                closing=tone_cfg["closing"],
                signature=tone_cfg["signature"],
            )
        except Exception as e:  # noqa: BLE001
            warnings.append(f"template format failed: {e}")
            email_text = BUILTIN.format(
                to=to,
                subject=subject,
                salutation=tone_cfg["salutation"],
                opening=tone_cfg["opening"],
                body="\n".join(body_lines),
                action=action,
                closing=tone_cfg["closing"],
                signature=tone_cfg["signature"],
            )
    else:
        email_text = BUILTIN.format(
            to=to,
            subject=subject,
            salutation=tone_cfg["salutation"],
            opening=tone_cfg["opening"],
            body="\n".join(body_lines),
            action=action,
            closing=tone_cfg["closing"],
            signature=tone_cfg["signature"],
        )

    llm_cfg = resolve_llm_config(params)
    llm_polish = {
        "enabled": bool(params.get("llm_polish", llm_cfg.get("polish", True))) and llm_cfg.get("base_url") and llm_cfg.get("model"),
        "used": False,
        "error": None,
    }
    if llm_polish["enabled"]:
        polished, err = polish_email(
            to=to,
            subject=subject,
            tone=tone,
            points=points,
            context_payload=context,
            template_text=email_text,
            llm_cfg=llm_cfg,
        )
        if polished:
            email_text = polished
            llm_polish["used"] = True
        else:
            llm_polish["error"] = err
            warnings.append(f"llm polish failed, keep template: {err}")

    fname = f"email_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    try:
        path = write_text_file(output_dir, fname, email_text)
    except Exception:  # noqa: BLE001
        import tempfile
        path = write_text_file(Path(tempfile.gettempdir()), fname, email_text)
        warnings.append(f"workspace not writable, saved to {path}")

    return {
        "skill": "email-draft",
        "ok": True,
        "to": to,
        "subject": subject,
        "tone": tone,
        "points": points,
        "output_path": str(path),
        "preview": email_text[:800],
        "warnings": warnings,
        "llm_polish": llm_polish,
        "fallback": None,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    raw = sys.stdin.read().strip() if not sys.stdin.isatty() else ""
    params = json.loads(raw) if raw else {
        arg.split("=", 1)[0]: arg.split("=", 1)[1]
        for arg in sys.argv[1:]
        if "=" in arg
    }
    print(json.dumps(run(params), ensure_ascii=False, indent=2))
