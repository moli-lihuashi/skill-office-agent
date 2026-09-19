"""SkillOfficeAgent orchestrator: route → plan → execute serial skills → summarize."""
from __future__ import annotations

import json
import time
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import AgentConfig
from .executor import SkillExecutor
from .llm import LLMClient
from .router import RoutePlan, SkillRouter
from .skill_registry import SkillRegistry


def _extract_params(query: str, skill: str) -> dict:
    """Heuristic param extraction from natural language (rule layer)."""
    params: dict[str, str] = {}
    # absolute windows path
    m = re.search(r"([A-Za-z]:\\[^\s，。；;]+)", query)
    if m:
        path = m.group(1).rstrip("，。.；;")
        if skill in {"file-search"}:
            # if path looks like directory use as root; file use as path
            if path.lower().endswith((".csv", ".xlsx", ".xls", ".tsv")):
                params["path"] = path
            else:
                params["root"] = path
        else:
            params["path"] = path
            params.setdefault("root", str(Path(path).parent))

    # extension filter
    ext_hits = re.findall(r"\b(csv|xlsx|xls|docx|pptx|pdf|txt|md|json)\b", query, flags=re.I)
    if ext_hits and skill == "file-search":
        params["ext"] = ",".join(dict.fromkeys(e.lower() for e in ext_hits))

    # quoted or 「」 keywords for search
    qm = re.search(r"[“\"]([^”\"]{2,80})[”\"]|「([^」]{2,80})」", query)
    if qm:
        params["query"] = qm.group(1) or qm.group(2)
        if skill == "web-search":
            params["query"] = qm.group(1) or qm.group(2)

    # group-by (按/根据 + column + 统计/汇总/分组)
    gm = re.search(r"(?:按|根据)\s*([A-Za-z0-9_一-鿿]{1,20}?)\s*(?:分组|汇总|统计|归类|的)", query)
    if gm and skill == "table-stats":
        params["group_by"] = gm.group(1)
    gm2 = re.search(r"(?:按|根据)\s*([A-Za-z0-9_一-鿿]{1,20})\s*(?:分组|归类)", query)
    if gm2 and skill == "table-stats":
        params["group_by"] = gm2.group(1)

    # agg column: prefer explicit "销售额/金额" etc.
    if skill == "table-stats":
        prefer = re.search(r"(销售额|金额|工资|薪资|总量|数量|销量)", query)
        if prefer:
            params["agg_col"] = prefer.group(1)
        sm = re.search(r"(sum|mean|average|count|min|max|总和|平均|计数|最大|最小)", query, flags=re.I)
        if sm:
            mapping = {"总和": "sum", "sum": "sum", "平均": "mean", "mean": "mean", "average": "mean",
                       "计数": "count", "count": "count", "最大": "max", "max": "max", "最小": "min", "min": "min"}
            params["agg_func"] = mapping.get(sm.group(1).lower(), mapping.get(sm.group(1), "sum"))

    # email / report subject-ish
    if skill == "report-gen":
        title_m = re.search(r"(?:生成|写|出)?\s*([一-鿿A-Za-z0-9_]{2,12})\s*(?:报告|总结)", query)
        if title_m:
            word = title_m.group(1)
            if word not in {"起草", "同步", "一封", "一下", "详细", "完整"}:
                params["title"] = f"{word}报告"
            else:
                params["title"] = "任务处理报告"
        else:
            params["title"] = "任务处理报告"
    if skill == "email-draft":
        if "同事" in query or "项目组" in query:
            params["to"] = "项目组" if "项目组" in query else "同事"
        elif "领导" in query or "老板" in query:
            params["to"] = "领导"
        elif "客户" in query:
            params["to"] = "客户"
        sm = re.search(r"主题[:：]?\s*([^\n]{2,40})", query)
        if sm:
            params["subject"] = sm.group(1)
        else:
            params["subject"] = "工作同步"

    # web-search query: use full query if no explicit keyword
    if skill == "web-search" and not params.get("query"):
        cleaned = re.sub(r"(查一下|搜索一下|帮我查|网上查|查查|调研一下|搜索|查询|查)", "", query)
        cleaned = cleaned.strip(" ，。,")
        params["query"] = cleaned or query

    if skill == "file-search" and not params.get("query"):
        cleaned = re.sub(r"(帮我)?(找一下|找到|查找|搜索|检索|locate|find|search|找)", "", query, flags=re.I)
        cleaned = re.sub(r"(并|然后|再).*", "", cleaned)
        cleaned = cleaned.strip(" ，。,的文件文档Excel表格CSV")
        # prefer filename-like tokens; also keep Chinese nouns that may appear in content
        token = re.search(r"([A-Za-z0-9_\-\.]{3,}|销售|员工|报表|数据|邮件|报告)", cleaned)
        params["query"] = (token.group(1) if token else cleaned) or "*"

    return params


def _apply_extra_params(params: dict, skill: str, extra_params: dict | None) -> dict:
    """User-provided extras ALWAYS override heuristics."""
    if not extra_params:
        return params
    out = dict(params)
    skill_specific = extra_params.get(skill)
    if isinstance(skill_specific, dict):
        out.update(skill_specific)
    reserved = {"path", "root", "query", "ext", "group_by", "agg_col", "agg_func",
                "title", "subject", "to", "content", "timeout", "max_results",
                "output_dir", "format", "tone", "points", "context", "limit", "prefer_local"}
    for k, v in extra_params.items():
        if isinstance(v, dict):
            continue
        if k in reserved:
            out[k] = v
    return out


class SkillOfficeAgent:
    def __init__(self, config: AgentConfig | None = None, on_log: Callable[[str], None] | None = None):
        self.config = config or AgentConfig.load()
        self.on_log = on_log or self._default_log
        self.registry = SkillRegistry(self.config.skills_dir)
        self.router = SkillRouter(
            self.registry,
            min_score=self.config.router_min_score,
            enable_llm=self.config.enable_llm_router,
            llm_base_url=self.config.llm_base_url,
            llm_api_key=self.config.llm_api_key,
            llm_model=self.config.llm_model,
            llm_timeout=self.config.llm_timeout,
        )
        self.executor = SkillExecutor(
            root=self.config.root,
            default_timeout=self.config.default_timeout,
            default_retries=self.config.default_retries,
            backoff_factor=self.config.backoff_factor,
            on_log=self.on_log,
        )
        self.llm = LLMClient(
            self.config.llm_base_url,
            self.config.llm_api_key,
            self.config.llm_model,
            self.config.llm_timeout,
        )
        self.config.logs_dir.mkdir(parents=True, exist_ok=True)
        self._session_log: list[dict] = []

    @staticmethod
    def _default_log(msg: str) -> None:
        print(msg, flush=True)

    @property
    def agent_mode(self) -> str:
        return self.config.agent_mode

    def _llm_runtime_payload(self) -> dict:
        return {
            **self.llm.config_payload(),
            "polish": self.config.llm_polish,
        }

    def list_skills(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "keywords": s.keywords,
                "entry": s.entry,
                "timeout": s.timeout,
                "retries": s.retries,
                "fallback": s.fallback,
                "tools": s.tools,
            }
            for s in self.registry.list_skills()
        ]

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        result = self.executor.run_tool(name, arguments or {}, retries=self.config.default_retries)
        return result.to_dict()

    def route(self, query: str) -> dict:
        plan = self.router.route(query)
        return {
            "query": plan.query,
            "skills": plan.skills,
            "strategy": plan.strategy,
            "pipeline": plan.pipeline,
            "reason": plan.reason,
            "scores": [
                {"skill": m.skill, "score": round(m.score, 2), "reasons": m.reasons}
                for m in plan.scores
            ],
        }

    def run(
        self,
        query: str,
        extra_params: dict | None = None,
        skills: list[str] | None = None,
        mode: str | None = None,
    ) -> dict:
        """Execute user request.

        mode:
          - rule: pure skill pipeline (template + local tools)
          - llm_agent: LLM function-calling loop calls tools autonomously;
            falls back to rule path when LLM unavailable/fails
          - hybrid (default): rule skill chain; report/email may polish via LLM
        """
        t0 = time.time()
        mode = (mode or self.config.agent_mode or "hybrid").lower()
        if mode not in {"rule", "llm_agent", "hybrid"}:
            mode = "hybrid"

        plan = self.router.route(query) if not skills else RoutePlan(
            query=query, skills=skills, strategy="manual", reason="user-specified skills"
        )
        self.on_log(f"[route] strategy={plan.strategy} skills={plan.skills} reason={plan.reason} mode={mode}")

        llm_note = None
        results: list[dict] = []
        if mode == "llm_agent":
            llm_out = self._run_llm_agent(query, extra_params, plan)
            if llm_out.get("ok"):
                results = llm_out.get("results") or []
                llm_note = {
                    "mode": "llm_agent",
                    "answer": llm_out.get("answer", ""),
                    "tool_calls": [
                        {"name": c.get("name"), "arguments": c.get("arguments")}
                        for c in llm_out.get("tool_calls") or []
                    ],
                    "rounds": llm_out.get("rounds"),
                }
                errors = [] if llm_out.get("ok") else [llm_out.get("error") or "llm_agent failed"]
                degraded_skills = []
                for r in results:
                    data = r.get("data") or {}
                    if r.get("degraded") or data.get("degraded"):
                        degraded_skills.append(r.get("skill") or data.get("skill") or "tool")
                summary = self._summarize(
                    query,
                    RoutePlan(query=query, skills=[r.get("skill", "tool") for r in results],
                              strategy="llm_agent", reason=llm_out.get("answer", "")[:80] or "llm fc loop"),
                    results,
                )
                out = {
                    "ok": bool(llm_out.get("ok")),
                    "query": query,
                    "mode": "llm_agent",
                    "route": {
                        "skills": [r.get("skill") for r in results],
                        "strategy": "llm_agent",
                        "pipeline": None,
                        "reason": "LLM function-calling loop",
                    },
                    "results": results,
                    "llm": llm_note,
                    "summary": summary,
                    "errors": [e for e in [llm_out.get("error")] if e],
                    "degraded_skills": degraded_skills,
                    "elapsed_ms": int((time.time() - t0) * 1000),
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }
                self._persist_session(out)
                return out
            self.on_log(f"[llm_agent-fallback] {llm_out.get('error')}; use rule pipeline")
            llm_note = {"mode": "llm_agent", "fallback_to": "rule", "error": llm_out.get("error")}

        # rule / hybrid path (also llm_agent fallback)
        out = self._run_rule_pipeline(query, extra_params, plan, t0, mode=mode, llm_note=llm_note)
        self._persist_session(out)
        return out

    def _prepare_skill_params(self, query: str, name: str, extra_params: dict | None) -> dict:
        params = _extract_params(query, name)
        params = _apply_extra_params(params, name, extra_params)
        if name == "file-search" and params.get("path"):
            p = Path(str(params["path"]))
            params["query"] = p.stem
            if p.suffix:
                params["ext"] = p.suffix.lstrip(".")
            params["root"] = str(p.parent if p.suffix else p)
        if name in {"report-gen", "email-draft"}:
            params.setdefault("output_dir", str(self.config.workspace_dir))
            # inject LLM for optional final-text generation inside skill scripts
            if self.config.llm_polish and self.llm.available:
                params["llm"] = self._llm_runtime_payload()
                params["llm_polish"] = True
            else:
                params["llm_polish"] = False
        if name == "web-search":
            params.setdefault("timeout", self.config.search_timeout)
            params.setdefault("max_results", 5)
        return params

    def _run_rule_pipeline(
        self,
        query: str,
        extra_params: dict | None,
        plan: RoutePlan,
        t0: float,
        mode: str = "rule",
        llm_note: dict | None = None,
    ) -> dict:
        results: list[dict] = []
        pipeline_context: dict[str, Any] = {"results": results}
        errors: list[str] = []
        degraded_skills: list[str] = []

        for name in plan.skills:
            skill = self.registry.get(name)
            if not skill:
                errors.append(f"skill not found: {name}")
                continue
            params = self._prepare_skill_params(query, name, extra_params)
            exec_result = self.executor.run_skill(skill, params, pipeline_context)
            payload = exec_result.to_dict()
            # surface polish status
            data = payload.get("data") or {}
            if data.get("llm_polish"):
                payload["llm_polish"] = data.get("llm_polish")
            results.append(payload)
            if not exec_result.ok:
                errors.append(f"{name}: {exec_result.error}")
            if exec_result.degraded:
                degraded_skills.append(name)

        summary = self._summarize(query, plan, results)
        return {
            "ok": not errors or any(r.get("ok") for r in results),
            "query": query,
            "mode": mode,
            "route": {
                "skills": plan.skills,
                "strategy": plan.strategy,
                "pipeline": plan.pipeline,
                "reason": plan.reason,
            },
            "results": results,
            "llm": llm_note,
            "summary": summary,
            "errors": errors,
            "degraded_skills": degraded_skills,
            "elapsed_ms": int((time.time() - t0) * 1000),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }

    def _llm_agent_system_prompt(self) -> str:
        catalog = self.registry.catalog_for_prompt()
        from tools import FUNCTION_CALLING_TOOLS
        tool_names = ", ".join(t["function"]["name"] for t in FUNCTION_CALLING_TOOLS)
        return (
            "你是技能化办公 Agent。根据用户请求，通过 Function Calling 自主选择并调用本地工具完成任务。\n"
            "可用技能（领域说明，工具在 tools 列表中）：\n"
            f"{catalog}\n"
            f"可调用工具：{tool_names}\n"
            "原则：\n"
            "1. 需要本地数据时优先 search_files / describe_table / group_by_table。\n"
            "2. 网络信息用 search_web；失败可依赖 search_knowledge_base。\n"
            "3. 写报告/邮件时可用 write_file 落盘到 data/workspace。\n"
            "4. 不要编造文件路径或统计数据；以工具返回为准。\n"
            "5. 最后用中文简要总结你调用了哪些工具、得到了什么结论。"
        )

    def _normalize_llm_tool_results(self, tool_calls: list[dict]) -> list[dict]:
        """Map FC tool transcripts to skill-like result payloads."""
        mapped: list[dict] = []
        tool_to_skill = {
            "search_files": "file-search",
            "list_files": "file-search",
            "read_file_meta": "file-search",
            "describe_table": "table-stats",
            "group_by_table": "table-stats",
            "read_table": "table-stats",
            "search_web": "web-search",
            "search_knowledge_base": "web-search",
            "write_file": "report-gen",
        }
        for c in tool_calls:
            name = c.get("name") or "tool"
            result = c.get("result") or {}
            skill = tool_to_skill.get(name, f"tool:{name}")
            data = dict(result) if isinstance(result, dict) else {"value": result}
            mapped.append({
                "skill": skill,
                "ok": bool(data.get("ok", True)),
                "data": data,
                "attempts": 1,
                "elapsed_ms": 0,
                "error": data.get("error"),
                "error_type": None,
                "degraded": bool(data.get("degraded")),
                "fallback_used": (data.get("fallback") or {}).get("source") if isinstance(data.get("fallback"), dict) else None,
                "timeline": [{"via": f"llm_tool:{name}", "arguments": c.get("arguments")}],
            })
        return mapped

    def _run_llm_agent(
        self,
        query: str,
        extra_params: dict | None,
        plan: RoutePlan,
    ) -> dict:
        if not self.llm.available:
            return {"ok": False, "error": "llm_not_configured", "results": [], "tool_calls": [], "answer": ""}

        # hint user-provided params into the prompt
        hint = {}
        if extra_params:
            for k in ["path", "root", "query", "group_by", "agg_col", "agg_func", "title", "subject", "to", "output_dir"]:
                if k in extra_params and not isinstance(extra_params[k], dict):
                    hint[k] = extra_params[k]
        if not hint.get("output_dir"):
            hint["output_dir"] = str(self.config.workspace_dir)
        user_msg = query
        if hint:
            user_msg += "\n\n已知参数(JSON)：" + json.dumps(hint, ensure_ascii=False)

        self.on_log(f"[llm_agent] model={self.llm.model} rounds={self.config.llm_agent_max_rounds}")
        loop = self.llm.run_function_calling_loop(
            system=self._llm_agent_system_prompt(),
            user=user_msg,
            max_rounds=self.config.llm_agent_max_rounds,
        )
        if not loop.get("ok") and not loop.get("tool_calls"):
            return {
                "ok": False,
                "error": loop.get("error") or "llm_loop_failed",
                "results": [],
                "tool_calls": loop.get("tool_calls") or [],
                "answer": loop.get("answer") or "",
            }
        results = self._normalize_llm_tool_results(loop.get("tool_calls") or [])
        return {
            "ok": True,
            "error": loop.get("error"),
            "results": results,
            "tool_calls": loop.get("tool_calls") or [],
            "answer": loop.get("answer") or "",
            "rounds": loop.get("rounds"),
        }

    def _summarize(self, query: str, plan: RoutePlan, results: list[dict]) -> str:
        lines = [f"任务：{query}", f"路由策略：{plan.strategy} → 技能链：{' → '.join(plan.skills) or '(无)'}"]
        for r in results:
            status = "成功" if r.get("ok") else "失败"
            extra = "（降级）" if r.get("degraded") else ""
            data = r.get("data") or {}
            note = ""
            if data.get("count") is not None:
                note = f" count={data.get('count')}"
            if data.get("output_path"):
                note += f" → {data.get('output_path')}"
            if data.get("rows") is not None:
                note += f" rows={data.get('rows')}"
            polish = data.get("llm_polish")
            if isinstance(polish, dict):
                if polish.get("used"):
                    note += " llm=used"
                elif polish.get("enabled"):
                    note += " llm=enabled"
                elif polish.get("error"):
                    note += f" llm=fail({str(polish.get('error'))[:40]})"
            if r.get("error"):
                note += f" err={str(r['error'])[:80]}"
            lines.append(f"  - {r.get('skill')}: {status}{extra}{note} ({r.get('elapsed_ms')}ms)")
        return "\n".join(lines)

    def _persist_session(self, out: dict) -> None:
        try:
            path = self.config.logs_dir / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
            path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            self._session_log.append({"path": str(path), "query": out.get("query")})
        except Exception as e:  # noqa: BLE001
            self.on_log(f"[log-error] {e}")
