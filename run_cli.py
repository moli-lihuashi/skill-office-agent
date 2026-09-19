#!/usr/bin/env python3
"""CLI entry for Skill Office Agent."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.agent import SkillOfficeAgent  # noqa: E402
from agent.config import AgentConfig  # noqa: E402


def print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def cmd_skills(agent: SkillOfficeAgent) -> None:
    skills = agent.list_skills()
    print(f"已加载 {len(skills)} 个技能（skills/ 下的 SKILL.md）\n")
    for s in skills:
        print(f"- {s['name']}")
        print(f"  描述: {s['description'][:120]}")
        print(f"  关键词: {', '.join(s['keywords'][:8])}")
        print(f"  入口: {s['entry']}  超时: {s['timeout']}s  重试: {s['retries']}  降级: {s['fallback']}")
        print()


def cmd_route(agent: SkillOfficeAgent, query: str) -> None:
    print_json(agent.route(query))


def cmd_tools(agent: SkillOfficeAgent) -> None:
    from tools import FUNCTION_CALLING_TOOLS
    print(f"Function Calling 工具共 {len(FUNCTION_CALLING_TOOLS)} 个：\n")
    for t in FUNCTION_CALLING_TOOLS:
        fn = t["function"]
        print(f"- {fn['name']}: {fn['description']}")
    print("\n可用 call-tool 直接调用，例如：")
    print('  python run_cli.py call-tool search_files --args \'{"query":"sales","root":"D:/skill-office-agent/data"}\'')


def cmd_call_tool(agent: SkillOfficeAgent, name: str, args: dict) -> None:
    print_json(agent.call_tool(name, args))


def cmd_run(agent: SkillOfficeAgent, query: str, args: dict, skills: list[str] | None, raw: bool) -> None:
    def log(msg: str) -> None:
        if not raw:
            print(f"  · {msg}", file=sys.stderr)

    agent.on_log = log
    result = agent.run(query, extra_params=args or None, skills=skills)
    if raw:
        print_json(result)
        return
    print("=" * 60)
    print("Skill Office Agent 执行结果")
    print("=" * 60)
    print(result.get("summary", ""))
    print("-" * 60)
    for r in result.get("results", []):
        data = r.get("data") or {}
        print(f"\n[{r.get('skill')}] ok={r.get('ok')} degraded={r.get('degraded')} "
              f"attempts={r.get('attempts')} elapsed={r.get('elapsed_ms')}ms")
        if r.get("fallback_used"):
            print(f"  fallback: {r['fallback_used']}")
        if data.get("files"):
            print(f"  文件 {data.get('count')} 个：")
            for f in data["files"][:8]:
                print(f"    - {f.get('path')}")
        if data.get("numeric_describe"):
            print("  数值统计：")
            for col, st in list((data.get("numeric_describe") or {}).items())[:5]:
                print(f"    - {col}: mean={st.get('mean')}, min={st.get('min')}, max={st.get('max')}")
        if data.get("group_result"):
            gr = data["group_result"]
            print(f"  分组 {gr.get('group_by')} → {gr.get('agg_col')} ({gr.get('agg_func')})：")
            for row in (gr.get("values") or [])[:8]:
                print(f"    - {row.get('key')}: {row.get('value')}")
        if data.get("results") and isinstance(data["results"], list) and r.get("skill") in {"web-search", "local-kb"}:
            print("  信息条目：")
            for item in data["results"][:5]:
                if isinstance(item, dict):
                    print(f"    - {item.get('title')}: {str(item.get('snippet') or item.get('url') or '')[:80]}")
        if data.get("output_path"):
            print(f"  输出文件: {data['output_path']}")
        if data.get("preview") and not data.get("files"):
            preview = str(data["preview"])[:400].replace("\n", "\n    ")
            print(f"  预览:\n    {preview}")
        if r.get("error"):
            print(f"  错误: {r['error']}")
    if result.get("errors"):
        print("\n错误列表:")
        for e in result["errors"]:
            print(f"  - {e}")
    print("\n完整 JSON 可用 --json 查看")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="skill-office-agent",
        description="基于 SKILL.md 的技能化办公 Agent",
    )
    p.add_argument("--config", help="config.json 路径", default=None)
    sub = p.add_subparsers(dest="command")

    sub.add_parser("skills", help="列出已加载技能")
    sub.add_parser("tools", help="列出 Function Calling 工具")

    pr = sub.add_parser("route", help="仅查看意图路由结果")
    pr.add_argument("query", nargs="+")

    pt = sub.add_parser("call-tool", help="直接调用某个工具（Function Calling）")
    pt.add_argument("tool_name")
    pt.add_argument("--args", default="", help="JSON 参数")
    pt.add_argument("--args-file", default="", help="从 JSON 文件读取工具参数")

    pe = sub.add_parser("run", help="执行用户请求（自动路由多技能）")
    pe.add_argument("query", nargs="+")
    pe.add_argument("--args", default="", help="额外参数 JSON，可为 {skill: {...}} 或全局键")
    pe.add_argument("--args-file", default="", help="从 JSON 文件读取额外参数（避免 shell 引号问题）")
    pe.add_argument("--skills", default="", help="手动指定技能链，逗号分隔")
    pe.add_argument("--mode", default="", choices=["", "rule", "llm_agent", "hybrid"],
                    help="执行模式：rule=纯规则技能链；llm_agent=模型FC自主调工具；hybrid=规则+可选润色（默认读 config.agent.mode）")
    pe.add_argument("--json", action="store_true", help="输出完整 JSON")

    sub.add_parser("desktop", help="启动桌面 GUI（等价于 run_desktop.py）")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    cfg = AgentConfig.load(ns.config)
    agent = SkillOfficeAgent(cfg)

    cmd = ns.command or "run"
    if cmd == "skills":
        cmd_skills(agent)
        return 0
    if cmd == "tools":
        cmd_tools(agent)
        return 0
    if cmd == "route":
        cmd_route(agent, " ".join(ns.query))
        return 0
    if cmd == "call-tool":
        args_file = getattr(ns, "args_file", "") or ""
        args_raw = getattr(ns, "args", "") or ""
        try:
            if args_file:
                args = json.loads(Path(args_file).read_text(encoding="utf-8"))
            else:
                args = json.loads(args_raw or "{}")
        except (OSError, json.JSONDecodeError) as e:
            print(f"工具参数无效: {e}", file=sys.stderr)
            return 2
        cmd_call_tool(agent, ns.tool_name, args)
        return 0
    if cmd == "desktop":
        import run_desktop  # type: ignore
        return run_desktop.main()
    if cmd == "run":
        query = " ".join(getattr(ns, "query", []) or [])
        args: dict = {}
        args_file = getattr(ns, "args_file", "") or ""
        args_raw = getattr(ns, "args", "") or ""
        if args_file:
            try:
                args = json.loads(Path(args_file).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                print(f"--args-file 读取失败: {e}", file=sys.stderr)
                return 2
        elif args_raw:
            try:
                args = json.loads(args_raw)
            except json.JSONDecodeError as e:
                print(f"--args 不是合法 JSON: {e}", file=sys.stderr)
                return 2
        if not query:
            # interactive mode
            print("Skill Office Agent 交互模式。输入 exit 退出，skills 查看技能。\n")
            while True:
                try:
                    line = input("agent> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if not line:
                    continue
                if line.lower() in {"exit", "quit"}:
                    break
                if line.lower() == "skills":
                    cmd_skills(agent)
                    continue
                cmd_run(agent, line, {}, None, raw=False)
            return 0
        skills = [s.strip() for s in ns.skills.split(",") if s.strip()] or None
        mode = (getattr(ns, "mode", "") or "").strip() or None
        raw_out = bool(getattr(ns, "json", False))

        def log(msg: str) -> None:
            if not raw_out:
                print(f"  · {msg}", file=sys.stderr)

        agent.on_log = log
        result = agent.run(query, extra_params=args, skills=skills, mode=mode)
        if raw_out:
            print_json(result)
            return 0
        print("=" * 60)
        print(f"Skill Office Agent 执行结果  mode={result.get('mode')}")
        print("=" * 60)
        print(result.get("summary", ""))
        print("-" * 60)
        for r in result.get("results", []):
            data = r.get("data") or {}
            print(f"\n[{r.get('skill')}] ok={r.get('ok')} degraded={r.get('degraded')} "
                  f"attempts={r.get('attempts')} elapsed={r.get('elapsed_ms')}ms")
            if r.get("fallback_used"):
                print(f"  fallback: {r['fallback_used']}")
            if data.get("llm_polish"):
                print(f"  llm_polish: {data['llm_polish']}")
            if data.get("files"):
                print(f"  文件 {data.get('count')} 个：")
                for f in data["files"][:8]:
                    print(f"    - {f.get('path')}")
            if data.get("numeric_describe"):
                print("  数值统计：")
                for col, st in list((data.get("numeric_describe") or {}).items())[:5]:
                    print(f"    - {col}: mean={st.get('mean')}, min={st.get('min')}, max={st.get('max')}")
            if data.get("group_result"):
                gr = data["group_result"]
                print(f"  分组 {gr.get('group_by')} → {gr.get('agg_col')} ({gr.get('agg_func')})：")
                for row in (gr.get("values") or [])[:8]:
                    print(f"    - {row.get('key')}: {row.get('value')}")
            if data.get("results") and isinstance(data["results"], list) and r.get("skill") in {"web-search", "local-kb"}:
                print("  信息条目：")
                for item in data["results"][:5]:
                    if isinstance(item, dict):
                        print(f"    - {item.get('title')}: {str(item.get('snippet') or item.get('url') or '')[:80]}")
            if data.get("output_path"):
                print(f"  输出文件: {data['output_path']}")
            if data.get("preview") and not data.get("files"):
                preview = str(data["preview"])[:400].replace("\n", "\n    ")
                print(f"  预览:\n    {preview}")
            if r.get("error"):
                print(f"  错误: {r['error']}")
        if result.get("llm"):
            print("\nLLM:")
            print("  " + json.dumps(result["llm"], ensure_ascii=False, default=str)[:800])
        if result.get("errors"):
            print("\n错误列表:")
            for e in result["errors"]:
                print(f"  - {e}")
        print("\n完整 JSON 可用 --json 查看")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
