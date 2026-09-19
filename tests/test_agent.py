"""End-to-end tests for Skill Office Agent."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.agent import SkillOfficeAgent, _extract_params  # noqa: E402
from agent.config import AgentConfig  # noqa: E402
from agent.router import SkillRouter  # noqa: E402
from agent.skill_registry import SkillRegistry, parse_skill_md  # noqa: E402
from tools import dispatch_tool  # noqa: E402
from tools.search import search_knowledge_base  # noqa: E402


class TestSkillRegistry(unittest.TestCase):
    def test_load_five_skills(self):
        reg = SkillRegistry(ROOT / "skills")
        self.assertGreaterEqual(len(reg.skills), 5)
        for name in ["file-search", "table-stats", "report-gen", "web-search", "email-draft"]:
            self.assertIn(name, reg.skills)
            meta = reg.skills[name]
            self.assertTrue(meta.description)
            self.assertTrue(meta.entry_path and meta.entry_path.exists(), name)

    def test_frontmatter_keywords(self):
        meta = parse_skill_md(ROOT / "skills" / "table-stats" / "SKILL.md")
        self.assertIsNotNone(meta)
        self.assertIn("统计", meta.keywords)


class TestRouter(unittest.TestCase):
    def setUp(self):
        self.reg = SkillRegistry(ROOT / "skills")
        self.router = SkillRouter(self.reg, enable_llm=False)

    def test_route_file_search(self):
        plan = self.router.route("帮我找一下销售相关的Excel文件")
        self.assertIn("file-search", plan.skills)

    def test_route_table_stats(self):
        plan = self.router.route("统计一下表格里的平均值和销售额")
        self.assertTrue(any(s == "table-stats" for s in plan.skills))

    def test_route_web_search_fallback_pipeline(self):
        plan = self.router.route("查一下远程办公趋势并写成报告")
        self.assertIn("web-search", plan.skills)
        self.assertIn("report-gen", plan.skills)
        self.assertEqual(plan.strategy, "pipeline")

    def test_route_multi_skill_pipeline(self):
        plan = self.router.route("找到销售表并统计各区域销售额，生成报告")
        self.assertEqual(plan.skills[0], "file-search")
        self.assertIn("table-stats", plan.skills)
        self.assertIn("report-gen", plan.skills)

    def test_email_draft(self):
        plan = self.router.route("给领导起草一封邮件同步本周数据")
        self.assertIn("email-draft", plan.skills)

    def test_explicit_skill_name(self):
        plan = self.router.route("使用 table-stats 分析数据")
        self.assertEqual(plan.skills, ["table-stats"])


class TestTools(unittest.TestCase):
    def test_search_files(self):
        res = dispatch_tool("search_files", {
            "root": str(ROOT / "data"),
            "query": "sales",
            "ext": "csv",
        })
        self.assertTrue(res["ok"])
        self.assertGreaterEqual(res["count"], 1)

    def test_describe_table(self):
        res = dispatch_tool("describe_table", {
            "path": str(ROOT / "data" / "samples" / "sales_2024.csv"),
        })
        self.assertTrue(res["ok"])
        self.assertIn("numeric_describe", res)
        self.assertIn("sales", res["numeric_describe"])

    def test_knowledge_base(self):
        hits = search_knowledge_base("远程办公", limit=3)
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0]["engine"], "local_knowledge_base")

    def test_group_by(self):
        res = dispatch_tool("group_by_table", {
            "path": str(ROOT / "data" / "samples" / "sales_2024.csv"),
            "group_by": "region",
            "agg_col": "sales",
            "agg_func": "sum",
        })
        self.assertTrue(res["ok"])
        values = res["group_result"]["values"]
        self.assertGreaterEqual(len(values), 2)


class TestParamExtract(unittest.TestCase):
    def test_group_by(self):
        p = _extract_params("按 region 统计销售额", "table-stats")
        self.assertEqual(p.get("group_by"), "region")

    def test_ext(self):
        p = _extract_params("找一下 csv 文件", "file-search")
        self.assertIn("csv", p.get("ext", ""))


class TestAgentE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent = SkillOfficeAgent(AgentConfig.load(), on_log=lambda m: None)

    def test_table_stats_pipeline(self):
        result = self.agent.run(
            "统计 sales 表格 按 region 的销售额",
            extra_params={"path": str(ROOT / "data" / "samples" / "sales_2024.csv"),
                          "group_by": "region", "agg_col": "sales", "agg_func": "sum"},
        )
        self.assertTrue(result["ok"])
        stats = next((r for r in result["results"] if r["skill"] == "table-stats"), None)
        self.assertIsNotNone(stats)
        self.assertTrue(stats["ok"])
        gr = (stats.get("data") or {}).get("group_result")
        self.assertIsNotNone(gr)
        self.assertGreaterEqual(len(gr.get("values") or []), 2)

    def test_multi_skill_serial(self):
        result = self.agent.run("找到销售表并统计各区域销售额，生成报告")
        skills = [r["skill"] for r in result["results"]]
        self.assertIn("file-search", skills)
        self.assertIn("table-stats", skills)
        self.assertIn("report-gen", skills)
        # report should be written
        rep = next(r for r in result["results"] if r["skill"] == "report-gen")
        self.assertTrue(rep["ok"])
        path = (rep.get("data") or {}).get("output_path")
        self.assertTrue(path and Path(path).exists())

    def test_web_search_degrades_to_kb(self):
        # force a nonsense/offline query; web may fail → knowledge base fallback
        result = self.agent.run("搜索一下 量子办公协作不存在的主题xyzabc123", skills=["web-search"])
        self.assertTrue(result["ok"] or result["results"])
        ws = result["results"][0]
        self.assertEqual(ws["skill"], "web-search")
        # either web ok or degraded fallback present
        self.assertTrue(ws["ok"] or ws.get("data", {}).get("fallback") or ws.get("fallback_used"))

    def test_email_draft_with_context(self):
        result = self.agent.run(
            "给领导起草一封邮件同步本周数据",
            extra_params={
                "subject": "本周销售数据同步",
                "to": "领导",
                "context": [{
                    "skill": "table-stats",
                    "path": "sales_2024.csv",
                    "rows": 10,
                    "cols": 5,
                    "numeric_describe": {"sales": {"mean": 262200, "min": 120000, "max": 540000}},
                    "group_result": {
                        "group_by": "region",
                        "agg_func": "sum",
                        "values": [{"key": "华东", "value": 1020000}],
                    },
                }],
            },
        )
        self.assertTrue(result["ok"])
        email = next(r for r in result["results"] if r["skill"] == "email-draft")
        self.assertTrue(email["ok"])
        path = (email.get("data") or {}).get("output_path")
        self.assertTrue(path and Path(path).exists())

    def test_fault_tolerance_retry_recorded(self):
        # missing path skill still returns structured result (no crash)
        result = self.agent.run("统计表格数据", skills=["table-stats"], extra_params={"path": "D:\\not\\exist\\x.csv"})
        self.assertIn("results", result)
        self.assertEqual(result["results"][0]["skill"], "table-stats")

    def test_tool_timeout_retry_layer(self):
        res = self.agent.call_tool("search_files", {"root": str(ROOT / "data"), "query": "employees"})
        self.assertTrue(res["ok"])


class TestLLMIntegration(unittest.TestCase):
    def test_config_modes(self):
        cfg = AgentConfig.load()
        self.assertIn(cfg.agent_mode, {"rule", "llm_agent", "hybrid"})
        self.assertTrue(cfg.llm_polish)

    def test_llm_not_configured_fallback(self):
        agent = SkillOfficeAgent(AgentConfig.load(), on_log=lambda m: None)
        # force unavailable LLM
        agent.llm.base_url = ""
        agent.llm.api_key = ""
        agent.llm.model = ""
        agent.config.llm_polish = True
        agent.config.agent_mode = "llm_agent"
        result = agent.run("统计表格数据", skills=["table-stats"], extra_params={
            "path": str(ROOT / "data" / "samples" / "sales_2024.csv"),
            "group_by": "region", "agg_col": "sales", "agg_func": "sum",
        }, mode="llm_agent")
        # should fall back to rule pipeline
        self.assertEqual(result.get("mode"), "llm_agent")
        self.assertTrue(result.get("results"))
        self.assertEqual(result["results"][0]["skill"], "table-stats")
        self.assertTrue(result["llm"] and result["llm"].get("fallback_to") == "rule")

    def test_hybrid_rule_path_without_llm(self):
        agent = SkillOfficeAgent(AgentConfig.load(), on_log=lambda m: None)
        agent.llm.base_url = ""
        agent.llm.model = ""
        result = agent.run(
            "生成报告",
            skills=["report-gen"],
            extra_params={
                "title": "测试报告",
                "context": [{"skill": "table-stats", "rows": 3, "cols": 2,
                             "numeric_describe": {"sales": {"mean": 1, "min": 0, "max": 2}}}],
            },
            mode="hybrid",
        )
        self.assertEqual(result.get("mode"), "hybrid")
        rep = result["results"][0]
        self.assertTrue(rep["ok"])
        polish = (rep.get("data") or {}).get("llm_polish") or {}
        self.assertFalse(polish.get("used", False))
        path = (rep.get("data") or {}).get("output_path")
        self.assertTrue(path and Path(path).exists())

    def test_llm_client_payload_roundtrip(self):
        from agent.llm import LLMClient
        c = LLMClient("https://example.com/v1", "k", "m", 12)
        p = c.config_payload()
        c2 = LLMClient.from_payload(p)
        self.assertTrue(c2.available)
        self.assertEqual(c2.model, "m")
        self.assertEqual(c2.timeout, 12.0)

    def test_resolve_llm_config_from_params(self):
        from tools.llm_text import llm_available, resolve_llm_config
        cfg = resolve_llm_config({"llm": {"base_url": "http://127.0.0.1:9/v1", "model": "x", "api_key": "t"}})
        self.assertTrue(cfg["base_url"])
        self.assertTrue(llm_available(cfg))
        empty = resolve_llm_config({"llm": {"base_url": "", "model": ""}})
        # env/config may still fill in; at least returns keys
        self.assertIn("base_url", empty)

    def test_run_accepts_mode_rule(self):
        agent = SkillOfficeAgent(AgentConfig.load(), on_log=lambda m: None)
        result = agent.run(
            "统计 sales 按 region",
            extra_params={
                "path": str(ROOT / "data" / "samples" / "sales_2024.csv"),
                "group_by": "region", "agg_col": "sales", "agg_func": "sum",
            },
            mode="rule",
        )
        self.assertEqual(result["mode"], "rule")
        self.assertTrue(result["results"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
