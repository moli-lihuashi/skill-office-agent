#!/usr/bin/env python3
"""Desktop GUI for Skill Office Agent (tkinter)."""
from __future__ import annotations

import json
import queue
import sys
import threading
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from agent.agent import SkillOfficeAgent
from agent.config import AgentConfig


class AgentDesktop(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Skill Office Agent — 技能化办公助手")
        self.geometry("980x680")
        self.minsize(860, 560)
        self.cfg = AgentConfig.load()
        self.agent = SkillOfficeAgent(self.cfg, on_log=self._log_safe)
        self.q: queue.Queue = queue.Queue()
        self._build_styles()
        self._build_ui()
        self._load_skills()
        self.after(200, self._poll_queue)

    # ---------- UI ----------
    def _build_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:  # noqa: BLE001
            pass
        style.configure("TButton", padding=6)
        style.configure("TLabelframe.Label", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Header.TLabel", font=("Microsoft YaHei UI", 12, "bold"))

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        header = ttk.Frame(self)
        header.pack(fill="x", **pad)
        ttk.Label(header, text="基于 SKILL.md 的技能化办公 Agent", style="Header.TLabel").pack(side="left")
        self.status_var = tk.StringVar(value=f"工作区: {self.cfg.workspace_dir}")
        ttk.Label(header, textvariable=self.status_var).pack(side="right")

        # input area
        frm_in = ttk.LabelFrame(self, text="用户意图")
        frm_in.pack(fill="x", **pad)
        self.input = tk.Text(frm_in, height=4, wrap="word", font=("Microsoft YaHei UI", 10))
        self.input.pack(fill="x", padx=8, pady=6)
        self.input.insert("1.0", "找到销售表并统计各区域销售额，生成报告并起草同步邮件")

        btn_row = ttk.Frame(frm_in)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btn_row, text="执行 (Run)", command=self.on_run).pack(side="left", padx=4)
        ttk.Button(btn_row, text="仅路由 (Route)", command=self.on_route).pack(side="left", padx=4)
        ttk.Button(btn_row, text="刷新技能", command=self._load_skills).pack(side="left", padx=4)
        ttk.Button(btn_row, text="清空输出", command=lambda: self.out.delete("1.0", "end")).pack(side="left", padx=4)
        ttk.Button(btn_row, text="导出 JSON", command=self.on_export).pack(side="right", padx=4)

        # middle: skills + tools
        mid = ttk.Panedwindow(self, orient="horizontal")
        mid.pack(fill="both", expand=True, **pad)

        left = ttk.Frame(mid)
        right = ttk.Frame(mid)
        mid.add(left, weight=1)
        mid.add(right, weight=2)

        frm_skills = ttk.LabelFrame(left, text="技能目录 (SKILL.md)")
        frm_skills.pack(fill="both", expand=True)
        cols = ("name", "timeout", "fallback")
        self.skill_tree = ttk.Treeview(frm_skills, columns=cols, show="headings", height=12)
        self.skill_tree.heading("name", text="技能")
        self.skill_tree.heading("timeout", text="超时")
        self.skill_tree.heading("fallback", text="降级")
        self.skill_tree.column("name", width=120)
        self.skill_tree.column("timeout", width=60, anchor="center")
        self.skill_tree.column("fallback", width=100)
        self.skill_tree.pack(fill="both", expand=True, padx=6, pady=6)
        self.skill_detail = tk.Text(frm_skills, height=6, wrap="word", font=("Microsoft YaHei UI", 9))
        self.skill_detail.pack(fill="x", padx=6, pady=(0, 6))
        self.skill_tree.bind("<<TreeviewSelect>>", self._on_skill_select)

        frm_tools = ttk.LabelFrame(right, text="Function Calling 工具 / 执行输出")
        frm_tools.pack(fill="both", expand=True)
        self.out = tk.Text(frm_tools, wrap="word", font=("Consolas", 10))
        self.out.pack(fill="both", expand=True, padx=6, pady=6)

        # tool bar
        tool_bar = ttk.Frame(frm_tools)
        tool_bar.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Label(tool_bar, text="快捷工具:").pack(side="left")
        ttk.Button(tool_bar, text="search_files", command=lambda: self._quick_tool("search_files", {
            "root": str(self.cfg.data_dir), "query": "*", "limit": 20
        })).pack(side="left", padx=3)
        ttk.Button(tool_bar, text="search_knowledge_base", command=lambda: self._quick_tool("search_knowledge_base", {
            "query": "报告", "limit": 3
        })).pack(side="left", padx=3)
        ttk.Button(tool_bar, text="list_files", command=lambda: self._quick_tool("list_files", {
            "root": str(self.cfg.data_dir), "limit": 30
        })).pack(side="left", padx=3)

        # footer path pick
        foot = ttk.Frame(self)
        foot.pack(fill="x", **pad)
        ttk.Label(foot, text="输出目录:").pack(side="left")
        self.outdir_var = tk.StringVar(value=str(self.cfg.workspace_dir))
        ent = ttk.Entry(foot, textvariable=self.outdir_var)
        ent.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(foot, text="浏览…", command=self.on_browse_outdir).pack(side="left")

    def _load_skills(self) -> None:
        self.agent.registry.reload()
        for i in self.skill_tree.get_children():
            self.skill_tree.delete(i)
        for s in self.agent.list_skills():
            self.skill_tree.insert("", "end", iid=s["name"], values=(
                s["name"], s["timeout"], s["fallback"] or "-"
            ))
        # tools listing
        self._log("\n==== 已加载技能 ====")
        for s in self.agent.list_skills():
            self._log(f"- {s['name']}: {s['description'][:80]}")
        self._log(f"\n==== Function Calling 工具 ({len(__import__('tools').FUNCTION_CALLING_TOOLS)}) ====")
        for t in __import__("tools").FUNCTION_CALLING_TOOLS:
            fn = t["function"]
            self._log(f"- {fn['name']}")
        self.status_var.set(
            f"技能 {len(self.agent.registry.skills)} 个 | mode={self.agent.agent_mode} | "
            f"LLM路由={'开' if self.agent.llm.available else '关(规则路由)'}"
        )

    def _on_skill_select(self, _event=None) -> None:
        sel = self.skill_tree.selection()
        self.skill_detail.delete("1.0", "end")
        if not sel:
            return
        meta = self.agent.registry.get(sel[0])
        if not meta:
            return
        self.skill_detail.insert(
            "1.0",
            f"name: {meta.name}\n"
            f"entry: {meta.entry}\n"
            f"keywords: {', '.join(meta.keywords)}\n"
            f"tools: {', '.join(meta.tools)}\n"
            f"description: {meta.description[:400]}",
        )

    def _quick_tool(self, name: str, args: dict) -> None:
        def worker():
            try:
                res = self.agent.call_tool(name, args)
                self.q.put(("log", f"\n[tool:{name}]\n" + json.dumps(res, ensure_ascii=False, indent=2, default=str)[:4000]))
            except Exception as e:  # noqa: BLE001
                self.q.put(("log", f"\n[tool-error:{name}] {e}"))
        threading.Thread(target=worker, daemon=True).start()

    def on_browse_outdir(self) -> None:
        path = filedialog.askdirectory(initialdir=self.outdir_var.get() or str(self.cfg.root))
        if path:
            self.outdir_var.set(path)

    def on_route(self) -> None:
        query = self.input.get("1.0", "end").strip()
        if not query:
            messagebox.showinfo("提示", "请先输入意图")
            return
        try:
            info = self.agent.route(query)
            self._log("\n==== 路由结果 ====\n" + json.dumps(info, ensure_ascii=False, indent=2))
        except Exception as e:  # noqa: BLE001
            self._log(f"\n[route-error] {e}\n{traceback.format_exc()}")

    def on_run(self) -> None:
        query = self.input.get("1.0", "end").strip()
        if not query:
            messagebox.showinfo("提示", "请先输入意图")
            return
        outdir = self.outdir_var.get().strip()
        self.status_var.set("执行中…")

        def worker():
            def log(msg: str) -> None:
                self.q.put(("log", "  · " + msg))
            self.agent.on_log = log
            try:
                extra = {"output_dir": outdir} if outdir else None
                result = self.agent.run(query, extra_params=extra)
                self.q.put(("result", result))
            except Exception as e:  # noqa: BLE001
                self.q.put(("error", f"{e}\n{traceback.format_exc()}"))

        self._log(f"\n\n==== RUN: {query} ====")
        threading.Thread(target=worker, daemon=True).start()

    def on_export(self) -> None:
        content = self.out.get("1.0", "end")
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("JSON", "*.json"), ("All", "*.*")],
            initialdir=str(self.cfg.workspace_dir),
        )
        if path:
            Path(path).write_text(content, encoding="utf-8")
            self._log(f"\n已导出: {path}")

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "result":
                    self._render_result(payload)
                    self.status_var.set("完成")
                elif kind == "error":
                    self._log(f"\n[error] {payload}")
                    self.status_var.set("失败")
        except queue.Empty:
            pass
        self.after(200, self._poll_queue)

    def _render_result(self, result: dict) -> None:
        self._log("\n==== 执行摘要 ====")
        self._log(result.get("summary", ""))
        self._log(f"耗时: {result.get('elapsed_ms')} ms | strategy={result.get('route', {}).get('strategy')}")
        for r in result.get("results", []):
            data = r.get("data") or {}
            self._log(f"\n[{r.get('skill')}] ok={r.get('ok')} degraded={r.get('degraded')} attempts={r.get('attempts')}")
            if r.get("fallback_used"):
                self._log(f"  fallback: {r['fallback_used']}")
            if data.get("output_path"):
                self._log(f"  output: {data['output_path']}")
            if data.get("count") is not None:
                self._log(f"  count: {data['count']}")
            if data.get("group_result"):
                gr = data["group_result"]
                self._log(f"  groupby: {gr.get('group_by')} -> {gr.get('agg_col')} ({gr.get('agg_func')})")
                for row in (gr.get("values") or [])[:8]:
                    self._log(f"    {row.get('key')}: {row.get('value')}")
            if r.get("error"):
                self._log(f"  error: {r['error']}")
        self._log("\n==== 完整 JSON（截断）====")
        self._log(json.dumps(result, ensure_ascii=False, indent=2, default=str)[:6000])

    def _log(self, msg: str) -> None:
        self.out.insert("end", msg + "\n")
        self.out.see("end")

    def _log_safe(self, msg: str) -> None:
        self.q.put(("log", msg))


def main() -> int:
    app = AgentDesktop()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
