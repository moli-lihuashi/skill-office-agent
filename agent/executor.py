"""Fault-tolerant tool/skill executor: timeout, retry, fallback, degradation."""
from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from .skill_registry import SkillMeta


@dataclass
class ExecResult:
    skill: str
    ok: bool
    data: dict = field(default_factory=dict)
    attempts: int = 0
    elapsed_ms: int = 0
    error: str | None = None
    error_type: str | None = None
    degraded: bool = False
    fallback_used: str | None = None
    timeline: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "ok": self.ok,
            "data": self.data,
            "attempts": self.attempts,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
            "error_type": self.error_type,
            "degraded": self.degraded,
            "fallback_used": self.fallback_used,
            "timeline": self.timeline,
        }


class CircuitOpen(RuntimeError):
    """Raised when a skill is temporarily blacklisted after repeated hard failures."""


class SkillExecutor:
    """Execute skill entry scripts with timeout/retry/fallback."""

    def __init__(
        self,
        root,
        default_timeout: float = 30,
        default_retries: int = 2,
        backoff_factor: float = 1.5,
        failure_threshold: int = 3,
        circuit_seconds: float = 60,
        on_log: Callable[[str], None] | None = None,
    ):
        self.root = root
        self.default_timeout = default_timeout
        self.default_retries = default_retries
        self.backoff_factor = backoff_factor
        self.failure_threshold = failure_threshold
        self.circuit_seconds = circuit_seconds
        self.on_log = on_log or (lambda msg: None)
        self._fail_counts: dict[str, int] = {}
        self._circuit_until: dict[str, float] = {}

    def _log(self, msg: str) -> None:
        self.on_log(msg)

    def _circuit_check(self, skill: str) -> None:
        until = self._circuit_until.get(skill, 0)
        if until and time.time() < until:
            raise CircuitOpen(f"circuit open for skill '{skill}' until +{int(until - time.time())}s")

    def _record_failure(self, skill: str) -> None:
        self._fail_counts[skill] = self._fail_counts.get(skill, 0) + 1
        if self._fail_counts[skill] >= self.failure_threshold:
            self._circuit_until[skill] = time.time() + self.circuit_seconds
            self._log(f"[circuit] OPEN skill={skill} for {self.circuit_seconds}s")
            self._fail_counts[skill] = 0

    def _record_success(self, skill: str) -> None:
        self._fail_counts[skill] = 0
        self._circuit_until.pop(skill, None)

    def run_tool(self, name: str, arguments: dict, timeout: float = 20, retries: int = 1) -> ExecResult:
        """Run a Function Calling tool via tools.dispatch_tool (in-process, still timed via retries)."""
        from tools import dispatch_tool

        start = time.time()
        attempts = 0
        last_err = None
        data: dict = {}
        timeline = []
        max_attempts = max(1, retries + 1)
        while attempts < max_attempts:
            attempts += 1
            t0 = time.time()
            try:
                # in-process tools are fast; timeout enforced by caller for script tools
                data = dispatch_tool(name, arguments)
                if not data.get("ok", True):
                    raise RuntimeError(data.get("error") or "tool returned ok=false")
                timeline.append({"attempt": attempts, "ms": int((time.time() - t0) * 1000), "ok": True})
                return ExecResult(
                    skill=f"tool:{name}",
                    ok=True,
                    data=data,
                    attempts=attempts,
                    elapsed_ms=int((time.time() - start) * 1000),
                    timeline=timeline,
                )
            except Exception as e:  # noqa: BLE001
                last_err = e
                timeline.append({"attempt": attempts, "ms": int((time.time() - t0) * 1000), "ok": False, "error": str(e)})
                if attempts < max_attempts:
                    sleep_s = self.backoff_factor ** (attempts - 1)
                    self._log(f"[retry] tool={name} attempt={attempts} sleep={sleep_s:.1f}s err={e}")
                    time.sleep(sleep_s)
        return ExecResult(
            skill=f"tool:{name}",
            ok=False,
            attempts=attempts,
            elapsed_ms=int((time.time() - start) * 1000),
            error=str(last_err),
            error_type=type(last_err).__name__ if last_err else None,
            timeline=timeline,
        )

    def run_skill(self, skill: SkillMeta, params: dict, pipeline_context: dict | None = None) -> ExecResult:
        from tools.python_runner import run_python_script

        self._circuit_check(skill.name)
        timeout = float(skill.timeout or self.default_timeout)
        retries = int(skill.retries if skill.retries is not None else self.default_retries)
        max_attempts = max(1, retries + 1)
        start = time.time()
        attempts = 0
        timeline: list[dict] = []
        last_err = None
        last_err_type = None
        merged = dict(params or {})
        # inject previous pipeline outputs for multi-skill serial calling
        if pipeline_context:
            merged["__pipeline__"] = pipeline_context
            # convenience: auto-fill common params
            prev = pipeline_context.get("results") or []
            for r in reversed(prev):
                d = r.get("data") or {}
                if skill.name == "table-stats" and not merged.get("path"):
                    for cand in d.get("files") or []:
                        if isinstance(cand, dict) and cand.get("path"):
                            p = cand["path"]
                            if str(p).lower().endswith((".csv", ".xlsx", ".xls")):
                                merged["path"] = p
                                break
                    if not merged.get("path") and d.get("path") and str(d.get("path")).lower().endswith((".csv", ".xlsx", ".xls")):
                        merged["path"] = d["path"]
                if skill.name == "table-stats" and not merged.get("query") and d.get("query"):
                    merged.setdefault("query", d.get("query"))
                if skill.name in {"report-gen", "email-draft"} and not merged.get("context"):
                    # pass full chain
                    merged["context"] = [x.get("data") for x in prev if isinstance(x, dict)]

        entry = skill.entry_path
        if not entry or not entry.exists():
            result = ExecResult(
                skill=skill.name,
                ok=False,
                error=f"entry not found: {entry}",
                error_type="missing_entry",
                elapsed_ms=int((time.time() - start) * 1000),
            )
            return self._apply_skill_fallback(skill, result, merged)

        while attempts < max_attempts:
            attempts += 1
            t0 = time.time()
            self._log(f"[skill] {skill.name} attempt={attempts}/{max_attempts} params_keys={list(merged.keys())}")
            raw = run_python_script(str(entry), merged, timeout=timeout)
            elapsed = int((time.time() - t0) * 1000)
            if raw.get("ok", True) and not raw.get("error"):
                timeline.append({"attempt": attempts, "ms": elapsed, "ok": True})
                self._record_success(skill.name)
                # strip pipeline echo from data to keep results clean
                data = {k: v for k, v in raw.items() if k != "__pipeline__"}
                return ExecResult(
                    skill=skill.name,
                    ok=True,
                    data=data,
                    attempts=attempts,
                    elapsed_ms=int((time.time() - start) * 1000),
                    timeline=timeline,
                    degraded=bool(data.get("degraded")),
                    fallback_used=(data.get("fallback") or {}).get("source") if isinstance(data.get("fallback"), dict) else data.get("fallback"),
                )

            last_err = raw.get("error") or "skill failed"
            last_err_type = raw.get("error_type") or "skill_error"
            timeline.append({"attempt": attempts, "ms": elapsed, "ok": False, "error": str(last_err)[:300]})
            self._log(f"[skill-fail] {skill.name} attempt={attempts} err={str(last_err)[:200]}")
            is_timeout = last_err_type == "timeout" or "timeout" in str(last_err).lower()
            # Network/timeouts rarely heal on immediate retry — degrade early when fallback exists
            if is_timeout and skill.fallback in {"knowledge_base", "template_only"}:
                self._log(f"[fallback-early] {skill.name} timeout → {skill.fallback}")
                break
            if attempts < max_attempts:
                sleep_s = self.backoff_factor ** (attempts - 1)
                self._log(f"[retry-sleep] {sleep_s:.1f}s")
                time.sleep(sleep_s)

        self._record_failure(skill.name)
        failed = ExecResult(
            skill=skill.name,
            ok=False,
            attempts=attempts,
            elapsed_ms=int((time.time() - start) * 1000),
            error=str(last_err),
            error_type=str(last_err_type),
            timeline=timeline,
        )
        return self._apply_skill_fallback(skill, failed, merged)

    def _apply_skill_fallback(self, skill: SkillMeta, result: ExecResult, params: dict) -> ExecResult:
        """Degraded path: knowledge_base / template_only / related skill."""
        fb = skill.fallback
        if not fb:
            return result
        self._log(f"[fallback] skill={skill.name} fallback={fb}")

        if fb == "knowledge_base":
            from tools.search import search_knowledge_base
            q = str(params.get("query") or params.get("subject") or skill.name)
            hits = search_knowledge_base(q, limit=5)
            result.degraded = True
            result.fallback_used = "knowledge_base"
            result.data = {
                "skill": skill.name,
                "ok": True,
                "degraded": True,
                "query": q,
                "results": hits,
                "fallback": {"source": "knowledge_base", "original_error": result.error},
                "warnings": [f"primary skill failed: {result.error}"],
            }
            result.ok = True
            result.error = None
            return result

        if fb == "template_only":
            result.degraded = True
            result.fallback_used = "template_only"
            result.data = {
                "skill": skill.name,
                "ok": True,
                "degraded": True,
                "title": params.get("title") or params.get("subject") or skill.name,
                "output_path": None,
                "preview": "（降级模板）上游执行失败，已生成占位输出结构。",
                "fallback": {"source": "template_only", "original_error": result.error},
                "warnings": ["template_only fallback activated"],
            }
            result.ok = True
            result.error = None
            return result

        return result
