"""Load SKILL.md packages into a searchable registry (progressive disclosure)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SkillMeta:
    name: str
    description: str
    keywords: list[str] = field(default_factory=list)
    entry: str = "scripts/run.py"
    timeout: float = 30.0
    retries: int = 2
    tools: list[str] = field(default_factory=list)
    fallback: str | None = None
    tags: list[str] = field(default_factory=list)
    path: Path | None = None
    body: str = ""

    @property
    def entry_path(self) -> Path | None:
        if not self.path:
            return None
        return (self.path / self.entry).resolve()

    def frontmatter_summary(self) -> str:
        """Compact text used for routing scoring."""
        return " ".join([self.name, self.description, " ".join(self.keywords), " ".join(self.tags)])


def _parse_simple_yaml_block(block: str) -> dict:
    """Minimal YAML subset parser for SKILL.md frontmatter (no PyYAML dependency)."""
    data: dict = {}
    lines = block.splitlines()
    i = 0
    current_key = None
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        # key: value or key:
        m = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            data[key] = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()] if inner else []
            current_key = key
        elif val.startswith("{") and val.endswith("}"):
            # ignore inline map
            data[key] = val
            current_key = key
        elif val == "":
            # possibly a flow list on next lines or multi-line; try parse following list items
            items = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if re.match(r"^\s+-\s+", nxt):
                    items.append(re.sub(r"^\s+-\s+", "", nxt).strip().strip("'\""))
                    j += 1
                elif re.match(r"^\s+\S", nxt) and not re.match(r"^\s+-\s+", nxt):
                    # value continuation
                    if isinstance(data.get(key), str):
                        data[key] = (data[key] + " " + nxt.strip()).strip()
                    j += 1
                else:
                    break
            if items:
                data[key] = items
            else:
                data[key] = ""
            current_key = key
            i = j - 1
        else:
            # strip quotes
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            data[key] = val
            current_key = key
        i += 1
    return data


def parse_skill_md(path: Path) -> SkillMeta | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    fm = _parse_simple_yaml_block(parts[1])
    body = parts[2].strip()
    name = str(fm.get("name") or path.parent.name)
    description = str(fm.get("description") or "")
    keywords = fm.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    tools = fm.get("tools") or []
    if isinstance(tools, str):
        tools = [tools]
    tags = fm.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    try:
        timeout = float(fm.get("timeout") or 30)
    except (TypeError, ValueError):
        timeout = 30
    try:
        retries = int(fm.get("retries") or 2)
    except (TypeError, ValueError):
        retries = 2
    return SkillMeta(
        name=name,
        description=description,
        keywords=[str(k) for k in keywords],
        entry=str(fm.get("entry") or "scripts/run.py"),
        timeout=timeout,
        retries=retries,
        tools=[str(t) for t in tools],
        fallback=fm.get("fallback") or None,
        tags=[str(t) for t in tags],
        path=path.parent.resolve(),
        body=body,
    )


class SkillRegistry:
    def __init__(self, skills_dir: Path):
        self.skills_dir = Path(skills_dir)
        self.skills: dict[str, SkillMeta] = {}
        self.reload()

    def reload(self) -> int:
        self.skills.clear()
        if not self.skills_dir.exists():
            return 0
        for child in sorted(self.skills_dir.iterdir()):
            if not child.is_dir():
                continue
            md = child / "SKILL.md"
            meta = parse_skill_md(md)
            if meta:
                self.skills[meta.name] = meta
        return len(self.skills)

    def get(self, name: str) -> SkillMeta | None:
        return self.skills.get(name)

    def list_skills(self) -> list[SkillMeta]:
        return list(self.skills.values())

    def catalog_for_prompt(self) -> str:
        lines = []
        for s in self.list_skills():
            lines.append(f"- {s.name}: {s.description[:200]}")
        return "\n".join(lines)
