#!/usr/bin/env python3
"""table-stats skill entry: descriptive stats + groupby for CSV/Excel."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.spreadsheet import describe_table, group_by_table, load_table, preview_table  # noqa: E402
from tools.filesystem import search_files  # noqa: E402


def _resolve_path(params: dict) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    path = params.get("path")
    if path and Path(path).exists():
        return str(path), warnings
    # auto-discover from data workspace
    hits = search_files(
        root=str(ROOT / "data"),
        query=params.get("query") or "*",
        exts=[".csv", ".xlsx", ".xls"],
        limit=5,
    )
    if hits:
        warnings.append(f"auto-selected table: {hits[0]['path']}")
        return hits[0]["path"], warnings
    return None, ["no table path provided and no csv/xlsx found"]


def run(params: dict) -> dict:
    path, warnings = _resolve_path(params)
    if not path:
        return {
            "skill": "table-stats",
            "ok": False,
            "error": "missing table path",
            "path": None,
            "warnings": warnings,
            "fallback": None,
        }

    group_by = params.get("group_by")
    agg_col = params.get("agg_col")
    agg_func = str(params.get("agg_func") or "sum").lower()
    head = int(params.get("head") or 5)

    try:
        df = load_table(path)
        desc_bundle = describe_table(df)
        profile = desc_bundle["profile"]
        numeric_describe = desc_bundle["numeric_describe"]
        preview = preview_table(df, head)
        group_result = None
        if group_by:
            # fuzzy column match
            cols = {c.lower().replace(" ", ""): c for c in df.columns}
            key = str(group_by).lower().replace(" ", "")
            resolved = cols.get(key) or next((c for k, c in cols.items() if key in k), None)
            if resolved is None:
                warnings.append(f"group_by column not found: {group_by}; available={list(df.columns)}")
            else:
                target = agg_col
                if target:
                    tkey = str(target).lower().replace(" ", "")
                    target = cols.get(tkey) or next((c for k, c in cols.items() if tkey in k), None)
                    if target is None:
                        # Chinese alias: 销售额/金额/销量/工资 → match numeric cols by hint
                        aliases = {
                            "销售额": ["sales", "amount", "revenue", "销售额"],
                            "金额": ["sales", "amount", "revenue"],
                            "销量": ["units", "qty", "quantity", "sales"],
                            "工资": ["salary", "薪资", "pay"],
                            "数量": ["units", "qty", "quantity", "count"],
                        }
                        for alias, cands in aliases.items():
                            if alias in str(agg_col) or str(agg_col) in alias:
                                for cand in cands:
                                    tkey2 = cand.lower()
                                    target = cols.get(tkey2) or next((c for k, c in cols.items() if tkey2 in k), None)
                                    if target:
                                        break
                            if target:
                                break
                    if target is None:
                        warnings.append(f"agg_col not found: {agg_col}; fallback to first numeric")
                group_result = group_by_table(df, resolved, target, agg_func)
    except Exception as e:  # noqa: BLE001
        kb_note = None
        kb = ROOT / "knowledge" / "office_kb.json"
        if kb.exists():
            try:
                kb_note = json.loads(kb.read_text(encoding="utf-8")).get("table_tips", [])[:3]
            except Exception:  # noqa: BLE001
                pass
        return {
            "skill": "table-stats",
            "ok": False,
            "error": str(e),
            "path": path,
            "warnings": warnings,
            "fallback": {"source": "local_knowledge_base", "table_tips": kb_note},
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }

    return {
        "skill": "table-stats",
        "ok": True,
        "path": path,
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "columns": list(map(str, df.columns)),
        "profile": profile,
        "numeric_describe": numeric_describe,
        "group_result": group_result,
        "preview": preview,
        "warnings": warnings,
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
