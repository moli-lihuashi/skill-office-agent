"""Intent router: match user query to skill(s), support multi-skill serial plans."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib import request as urlrequest
import json

from .skill_registry import SkillMeta, SkillRegistry

# Multi-skill serial pipelines: ordered skill names + combined intent patterns
PIPELINES = [
    {
        "name": "search_then_stats",
        "skills": ["file-search", "table-stats"],
        "patterns": [
            r"找.*统计", r"搜索.*分析", r"查找.*汇总", r"找出.*平均",
            r"find.*and.*analyz", r"search.*then.*stat",
        ],
        "hint": "定位表格并统计",
    },
    {
        "name": "stats_then_report",
        "skills": ["table-stats", "report-gen"],
        "patterns": [
            r"统计.*报告", r"分析.*报告", r"数据.*写.*报告",
            r"summar.*report", r"stats.*report",
        ],
        "hint": "先统计再写报告",
    },
    {
        "name": "search_stats_report",
        "skills": ["file-search", "table-stats", "report-gen"],
        "patterns": [
            r"找.*统计.*报告", r"查找.*分析.*生成报告",
            r"搜索.*汇总.*报告", r"找.*统计.*生成报告",
            r"找到.*统计.*报告",
        ],
        "hint": "检索→统计→报告",
    },
    {
        "name": "web_then_report",
        "skills": ["web-search", "report-gen"],
        "patterns": [
            r"查(一下|些)?.{0,12}(并|然后|再)?.{0,8}(写|生成|整理).{0,6}(报告|总结)",
            r"调研.*报告", r"搜索.*报告",
            r"search.*and.*report", r"research.*report",
        ],
        "hint": "网络调研并输出报告",
    },
    {
        "name": "stats_then_email",
        "skills": ["table-stats", "email-draft"],
        "patterns": [
            r"统计.*邮件", r"数据.*邮件", r"汇总.*邮件",
            r"stats.*email",
        ],
        "hint": "统计后起草邮件",
    },
    {
        "name": "report_then_email",
        "skills": ["report-gen", "email-draft"],
        "patterns": [
            r"报告.*邮件", r"写完报告.*发", r"生成报告.*邮件",
            r"report.*email",
        ],
        "hint": "报告落盘并起草邮件",
    },
    {
        "name": "search_stats_report_email",
        "skills": ["file-search", "table-stats", "report-gen", "email-draft"],
        "patterns": [
            r"找.*统计.*(报告|总结).*邮件",
            r"找.*统计.*报告.*起草",
            r"搜索.*统计.*报告.*邮件",
            r"找到.*统计.*报告.*邮件",
        ],
        "hint": "检索→统计→报告→邮件",
    },
    {
        "name": "stats_report_email",
        "skills": ["table-stats", "report-gen", "email-draft"],
        "patterns": [
            r"统计.*(报告|总结).*邮件",
            r"分析.*报告.*邮件",
        ],
        "hint": "统计→报告→邮件",
    },
    {
        "name": "web_report_email",
        "skills": ["web-search", "report-gen", "email-draft"],
        "patterns": [
            r"调研.*(报告|总结).*邮件",
            r"搜索.*报告.*邮件",
        ],
        "hint": "调研→报告→邮件",
    },
]


@dataclass
class RouteMatch:
    skill: str
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class RoutePlan:
    query: str
    skills: list[str]
    scores: list[RouteMatch] = field(default_factory=list)
    strategy: str = "keyword"  # keyword | pipeline | llm | fallback
    pipeline: str | None = None
    reason: str = ""


class SkillRouter:
    def __init__(self, registry: SkillRegistry, min_score: float = 2.0, enable_llm: bool = True,
                 llm_base_url: str = "", llm_api_key: str = "", llm_model: str = "", llm_timeout: float = 40):
        self.registry = registry
        self.min_score = min_score
        self.enable_llm = enable_llm
        self.llm_base_url = (llm_base_url or "").rstrip("/")
        self.llm_api_key = llm_api_key
        self.llm_model = llm_model
        self.llm_timeout = llm_timeout

    # ---------- scoring ----------
    def score_skill(self, query: str, skill: SkillMeta) -> RouteMatch:
        q = query.lower()
        score = 0.0
        reasons: list[str] = []

        for kw in skill.keywords:
            if not kw:
                continue
            k = kw.lower()
            if k in q:
                # longer keywords weigh more
                w = 2.0 + min(len(k), 12) * 0.15
                score += w
                reasons.append(f"keyword:{kw}")

        # token overlap with description
        q_tokens = set(re.findall(r"[a-z0-9_]{2,}|[一-鿿]{1,}", q))
        desc_tokens = set(re.findall(r"[a-z0-9_]{2,}|[一-鿿]{1,}", skill.description.lower() + " " + skill.name))
        overlap = q_tokens & desc_tokens
        # ignore very common weak tokens
        weak = {"的", "了", "一下", "帮我", "请", "the", "and", "for"}
        overlap = {t for t in overlap if t not in weak}
        if overlap:
            score += min(len(overlap) * 0.8, 4.0)
            reasons.append(f"overlap:{','.join(list(overlap)[:5])}")

        if skill.name.replace("-", "") in q.replace("-", "").replace(" ", ""):
            score += 5
            reasons.append("name_match")
        return RouteMatch(skill=skill.name, score=score, reasons=reasons)

    def rank(self, query: str) -> list[RouteMatch]:
        matches = [self.score_skill(query, s) for s in self.registry.list_skills()]
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches

    def detect_pipeline(self, query: str) -> dict | None:
        q = query.lower().replace(" ", "")
        matched: list[dict] = []
        for pipe in PIPELINES:
            if not all(self.registry.get(s) for s in pipe["skills"]):
                continue
            for pat in pipe["patterns"]:
                if re.search(pat, q) or re.search(pat, query):
                    matched.append(pipe)
                    break
        if not matched:
            return None
        # Prefer the longest/most complete skill chain (more specific intent wins)
        matched.sort(key=lambda p: (len(p["skills"]), len(p["patterns"][0])), reverse=True)
        return matched[0]

    # ---------- LLM router (OpenAI-compatible, optional) ----------
    def _llm_route(self, query: str) -> RoutePlan | None:
        if not (self.enable_llm and self.llm_base_url and self.llm_model):
            return None
        catalog = self.registry.catalog_for_prompt()
        tools = [{
            "type": "function",
            "function": {
                "name": "select_skills",
                "description": "根据用户意图选择要串行执行的技能列表",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skills": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "按执行顺序排列的技能 name",
                        },
                        "reason": {"type": "string"},
                    },
                    "required": ["skills", "reason"],
                },
            },
        }]
        body = {
            "model": self.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是技能路由器。根据用户意图从技能目录中选择一个或多个技能，"
                        "按串行执行顺序输出。不要编造不存在的技能名。\n技能目录：\n" + catalog
                    ),
                },
                {"role": "user", "content": query},
            ],
            "tools": tools,
            "tool_choice": {"type": "function", "function": {"name": "select_skills"}},
            "temperature": 0,
        }
        url = self.llm_base_url + "/chat/completions"
        req = urlrequest.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.llm_api_key}",
            },
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=self.llm_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            msg = data["choices"][0]["message"]
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                return None
            args = json.loads(tool_calls[0]["function"]["arguments"])
            skills = [s for s in args.get("skills") or [] if self.registry.get(s)]
            if not skills:
                return None
            return RoutePlan(
                query=query,
                skills=skills,
                strategy="llm",
                reason=args.get("reason") or "llm function-calling",
            )
        except Exception:  # noqa: BLE001
            return None

    def route(self, query: str) -> RoutePlan:
        query = (query or "").strip()
        if not query:
            return RoutePlan(query=query, skills=[], strategy="fallback", reason="empty query")

        # 1) explicit skill name in query
        for s in self.registry.list_skills():
            if s.name in query or s.name.replace("-", "") in query.replace(" ", "").replace("-", ""):
                return RoutePlan(
                    query=query,
                    skills=[s.name],
                    scores=[RouteMatch(s.name, 10, ["explicit_name"])],
                    strategy="keyword",
                    reason="explicit skill name",
                )

        # 2) multi-skill pipeline patterns
        pipe = self.detect_pipeline(query)
        if pipe:
            matches = [self.score_skill(query, self.registry.get(name)) for name in pipe["skills"] if self.registry.get(name)]
            return RoutePlan(
                query=query,
                skills=list(pipe["skills"]),
                scores=matches,
                strategy="pipeline",
                pipeline=pipe["name"],
                reason=pipe["hint"],
            )

        # 3) optional LLM function-calling router
        llm_plan = self._llm_route(query)
        if llm_plan and llm_plan.skills:
            return llm_plan

        # 4) hybrid keyword + description scoring
        matches = self.rank(query)
        top = [m for m in matches if m.score >= self.min_score]
        if top:
            # if second skill is close and query looks compound, keep serial chain
            primary = top[0].skill
            chain = [primary]
            if len(top) > 1 and top[1].score >= max(self.min_score, top[0].score * 0.65):
                # only chain complementary office flow pairs
                pairs = [
                    ("file-search", "table-stats"),
                    ("table-stats", "report-gen"),
                    ("web-search", "report-gen"),
                    ("table-stats", "email-draft"),
                    ("report-gen", "email-draft"),
                    ("file-search", "report-gen"),
                    ("web-search", "email-draft"),
                ]
                for a, b in pairs:
                    if primary == a and top[1].skill == b:
                        chain.append(b)
                    elif primary == b and top[1].skill == a:
                        chain.insert(0, a)
            return RoutePlan(
                query=query,
                skills=chain,
                scores=top,
                strategy="keyword",
                reason="scored match",
            )

        # 5) fallback: best score even if low, else web-search/report heuristic
        if matches:
            return RoutePlan(
                query=query,
                skills=[matches[0].skill],
                scores=matches[:3],
                strategy="fallback",
                reason="low confidence, best effort",
            )
        return RoutePlan(query=query, skills=["report-gen"], strategy="fallback", reason="no skills loaded")
