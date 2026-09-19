#!/usr/bin/env python3
"""web-search skill entry: web search with local knowledge-base fallback."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.search import search_knowledge_base, search_web  # noqa: E402


def run(params: dict) -> dict:
    query = str(params.get("query") or "").strip()
    max_results = int(params.get("max_results") or 5)
    timeout = float(params.get("timeout") or 8)
    prefer_local = bool(params.get("prefer_local"))
    warnings: list[str] = []

    if not query:
        return {
            "skill": "web-search",
            "ok": False,
            "degraded": False,
            "error": "query is required",
            "query": "",
            "results": [],
            "fallback": None,
            "warnings": warnings,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }

    results = []
    degraded = False
    fallback = None
    ok = True

    if prefer_local:
        warnings.append("prefer_local=true, skip network")
        results = search_knowledge_base(query, limit=max_results)
        degraded = True
        fallback = {"source": "knowledge_base", "reason": "prefer_local"}
    else:
        try:
            results = search_web(query, max_results=max_results, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"web search failed: {e}")
            results = []

        if not results:
            degraded = True
            warnings.append("empty web results; fallback to knowledge_base")
            kb_hits = search_knowledge_base(query, limit=max_results)
            fallback = {
                "source": "knowledge_base",
                "reason": "web_search_empty_or_failed",
                "hits": len(kb_hits),
            }
            results = kb_hits
            if not kb_hits:
                ok = False
                fallback["note"] = "本地知识库也无匹配，返回空结果但不抛出致命错误"

    return {
        "skill": "web-search",
        "ok": ok,
        "degraded": degraded,
        "query": query,
        "engine": "knowledge_base" if degraded else "web",
        "results": results,
        "count": len(results),
        "fallback": fallback,
        "warnings": warnings,
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
