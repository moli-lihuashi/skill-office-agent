"""Web search tools with local knowledge-base fallback. stdlib only."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB_PATH = ROOT / "knowledge" / "office_kb.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def http_get(url: str, timeout: float = 10.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="ignore")


def _strip_tags(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(re.sub(r"\s+", " ", text))
    return text.strip()


def search_duckduckgo(query: str, max_results: int = 5, timeout: float = 10.0) -> list[dict]:
    q = urllib.parse.quote(query)
    # html endpoint is simpler and often reachable without JS
    url = f"https://html.duckduckgo.com/html/?q={q}"
    html = http_get(url, timeout=timeout)
    results: list[dict] = []
    # anchors
    pattern = re.compile(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.I | re.S,
    )
    snippet_pattern = re.compile(
        r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
        re.I | re.S,
    )
    hrefs = pattern.findall(html)
    snippets = snippet_pattern.findall(html)
    for i, (href, title_html) in enumerate(hrefs):
        title = _strip_tags(title_html)
        href = urllib.parse.unquote(href)
        # ddg redirect links
        if "uddg=" in href:
            m = re.search(r"uddg=([^&]+)", href)
            if m:
                href = urllib.parse.unquote(m.group(1))
        snip = _strip_tags(snippets[i]) if i < len(snippets) else ""
        if not title:
            continue
        results.append({"title": title, "url": href, "snippet": snip, "engine": "duckduckgo"})
        if len(results) >= max_results:
            break
    return results


def search_web(query: str, max_results: int = 5, timeout: float = 10.0) -> list[dict]:
    """Try online engines; raise/return empty on failure (caller handles fallback)."""
    errors: list[str] = []
    # keep each engine probe short so skill-level timeout/fallback stays responsive
    t_ddg = min(float(timeout), 5.0)
    t_wiki = min(float(timeout), 3.0)
    try:
        hits = search_duckduckgo(query, max_results=max_results, timeout=t_ddg)
        if hits:
            return hits
        errors.append("duckduckgo empty")
    except Exception as e:  # noqa: BLE001
        errors.append(f"duckduckgo: {e}")

    # lightweight secondary probe: Wikipedia search API (often reachable)
    try:
        q = urllib.parse.quote(query)
        url = f"https://zh.wikipedia.org/w/api.php?action=opensearch&limit={max_results}&namespace=0&format=json&search={q}"
        raw = http_get(url, timeout=t_wiki)
        data = json.loads(raw)
        titles, descs, links = data[1], data[2], data[3]
        hits = [
            {"title": t, "url": u, "snippet": d, "engine": "wikipedia"}
            for t, d, u in zip(titles, descs, links)
        ]
        if hits:
            return hits
        errors.append("wikipedia empty")
    except Exception as e:  # noqa: BLE001
        errors.append(f"wikipedia: {e}")

    raise RuntimeError("all web engines failed: " + "; ".join(errors))


def _load_kb() -> dict:
    if not KB_PATH.exists():
        return {"articles": [], "file_hints": [], "table_tips": []}
    return json.loads(KB_PATH.read_text(encoding="utf-8"))


def _tokenize(text: str) -> list[str]:
    # CJK bigrams + latin words
    text = text.lower()
    words = re.findall(r"[a-z0-9_]{2,}|[一-鿿]{1,}", text)
    bigrams = []
    cjk_runs = re.findall(r"[一-鿿]+", text)
    for run in cjk_runs:
        if len(run) == 1:
            bigrams.append(run)
        else:
            bigrams.extend(run[i : i + 2] for i in range(len(run) - 1))
    return words + bigrams


def search_knowledge_base(query: str, limit: int = 5) -> list[dict]:
    kb = _load_kb()
    articles = kb.get("articles") or kb.get("entries") or []
    q_tokens = set(_tokenize(query))
    scored = []
    for art in articles:
        title = str(art.get("title") or art.get("name") or "")
        body = str(art.get("content") or art.get("summary") or art.get("snippet") or "")
        tags = " ".join(str(t) for t in (art.get("tags") or art.get("keywords") or []))
        hay = f"{title}\n{body}\n{tags}".lower()
        tokens = set(_tokenize(hay))
        score = len(q_tokens & tokens)
        # boost title hits
        if any(t in title.lower() for t in q_tokens):
            score += 3
        if score > 0:
            scored.append((score, art))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, art in scored[:limit]:
        out.append({
            "title": art.get("title") or art.get("name") or "KB entry",
            "url": art.get("url") or f"kb://{art.get('id', 'entry')}",
            "snippet": (art.get("content") or art.get("summary") or art.get("snippet") or "")[:300],
            "engine": "local_knowledge_base",
            "score": score,
        })
    return out
