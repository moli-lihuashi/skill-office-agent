"""Local filesystem tools for skill-office-agent."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

SKIP_DIRS = {
    ".git", ".gradle", "__pycache__", "node_modules", ".venv",
    "System Volume Information", "$RECYCLE.BIN",
}


def _stat_entry(path: Path, root: str) -> dict:
    try:
        st = path.stat()
        return {
            "path": str(path),
            "name": path.name,
            "ext": path.suffix.lower(),
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        }
    except OSError:
        return {
            "path": str(path),
            "name": path.name,
            "ext": path.suffix.lower(),
            "size": 0,
            "mtime": "",
        }


def list_files(root: str, exts: list[str] | None = None, limit: int = 200) -> list[dict]:
    root_path = Path(root)
    if not root_path.exists():
        return []
    wanted = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts or []}
    out: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            p = Path(dirpath) / name
            if wanted and p.suffix.lower() not in wanted:
                continue
            out.append(_stat_entry(p, root))
            if len(out) >= limit:
                return out
    out.sort(key=lambda x: x.get("mtime") or "", reverse=True)
    return out


def _match_name(name: str, query: str) -> bool:
    if query in {"*", "", "all"}:
        return True
    return query.lower() in name.lower()


def _match_content(path: Path, query: str) -> bool:
    if not query or query in {"*", ""}:
        return False
    try:
        if path.stat().st_size > 2_000_000:
            return False
        text = path.read_text(encoding="utf-8", errors="ignore")
        return query.lower() in text.lower()
    except OSError:
        return False


def search_files(
    root: str,
    query: str = "*",
    exts: list[str] | None = None,
    content: bool = False,
    limit: int = 20,
) -> list[dict]:
    candidates = list_files(root, exts=None, limit=50_000)
    wanted = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts or []}
    hits: list[dict] = []
    for item in candidates:
        p = Path(item["path"])
        if wanted and item["ext"] not in wanted:
            continue
        name_hit = _match_name(item["name"], query)
        content_hit = content and _match_content(p, query)
        if name_hit or content_hit or (content and query and query.lower() in item["name"].lower()):
            item = dict(item)
            item["match"] = "content" if content_hit and not name_hit else "name"
            hits.append(item)
            if len(hits) >= limit:
                break
    return hits


def read_file_meta(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"not found: {path}"}
    return {"ok": True, **_stat_entry(p, str(p.parent))}
