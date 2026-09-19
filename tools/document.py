"""Document helpers: templates fill + file write."""
from __future__ import annotations

from pathlib import Path


def write_text_file(directory: Path | str, filename: str, content: str) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(content, encoding="utf-8")
    return path.resolve()


def format_report(template: str, **kwargs) -> str:
    """Safe format: unknown placeholders remain unchanged."""
    class _Safe(dict):
        def __missing__(self, key):
            return "{" + key + "}"
    return template.format_map(_Safe(**kwargs))
