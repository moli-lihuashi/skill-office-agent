#!/usr/bin/env python3
"""file-search skill entry: locate local files by name/ext/content."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Allow running as subprocess from agent root
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.filesystem import search_files  # noqa: E402


def run(params: dict) -> dict:
    query = str(params.get("query") or "").strip() or "*"
    root = params.get("root") or str(ROOT / "data")
    ext_raw = params.get("ext") or ""
    limit = int(params.get("limit") or 20)
    content_mode = bool(params.get("content"))

    exts = []
    if isinstance(ext_raw, str) and ext_raw.strip():
        exts = [e if e.startswith(".") else f".{e}" for e in ext_raw.replace(" ", "").split(",") if e]

    warnings = []
    root_path = Path(root)
    if not root_path.exists():
        warnings.append(f"root not found: {root}, fallback to {ROOT / 'data'}")
        root_path = ROOT / "data"

    try:
        files = search_files(
            root=str(root_path),
            query=query,
            exts=exts or None,
            content=content_mode,
            limit=limit,
        )
    except Exception as e:  # noqa: BLE001
        return {
            "skill": "file-search",
            "ok": False,
            "error": str(e),
            "count": 0,
            "files": [],
            "root": str(root_path),
            "warnings": warnings,
            "fallback": None,
        }

    # widen search once if empty
    if not files and exts:
        warnings.append("no hits with ext filter; retry without ext")
        files = search_files(
            root=str(root_path),
            query=query,
            exts=None,
            content=content_mode,
            limit=limit,
        )

    fallback = None
    if not files:
        kb = ROOT / "knowledge" / "office_kb.json"
        if kb.exists():
            try:
                data = json.loads(kb.read_text(encoding="utf-8"))
                fallback = {
                    "source": "local_knowledge_base",
                    "file_hints": data.get("file_hints", [])[:5],
                    "note": "本地未命中，以下为知识库提示",
                }
            except Exception:  # noqa: BLE001
                pass

    return {
        "skill": "file-search",
        "ok": True,
        "count": len(files),
        "files": files,
        "root": str(root_path),
        "query": query,
        "ext": exts,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "warnings": warnings,
        "fallback": fallback,
    }


if __name__ == "__main__":
    raw = sys.stdin.read().strip() if not sys.stdin.isatty() else ""
    params = json.loads(raw) if raw else {
        arg.split("=", 1)[0]: arg.split("=", 1)[1]
        for arg in sys.argv[1:]
        if "=" in arg
    }
    result = run(params)
    print(json.dumps(result, ensure_ascii=False, indent=2))
