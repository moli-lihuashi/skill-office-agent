"""Tool package exports and Function Calling schema catalog."""
from __future__ import annotations

from . import document, filesystem, python_runner, search, spreadsheet  # noqa: F401

# OpenAI-style Function Calling schemas
FUNCTION_CALLING_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出目录下的文件，可按扩展名过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {"type": "string", "description": "根目录绝对路径"},
                    "ext": {"type": "string", "description": "扩展名，逗号分隔，如 xlsx,csv"},
                    "limit": {"type": "integer", "description": "最大返回条数"},
                },
                "required": ["root"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "按文件名/内容关键词在本地检索文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "query": {"type": "string"},
                    "ext": {"type": "string"},
                    "content": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_meta",
            "description": "读取文件元信息（大小、修改时间）。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_table",
            "description": "加载 CSV/Excel 表格并返回行列预览。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "head": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_table",
            "description": "对表格做描述性统计。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "group_by_table",
            "description": "按列分组聚合表格数据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "group_by": {"type": "string"},
                    "agg_col": {"type": "string"},
                    "agg_func": {"type": "string", "enum": ["sum", "mean", "count", "min", "max", "median"]},
                },
                "required": ["path", "group_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "网络信息检索；失败时可降级本地知识库。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "timeout": {"type": "number"},
                    "prefer_local": {"type": "boolean"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "检索本地办公知识库（网络搜索降级兜底）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "将文本内容写入本地文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string"},
                    "filename": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["directory", "filename", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python_script",
            "description": "以子进程方式运行 Python 脚本并传入 JSON 参数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_path": {"type": "string"},
                    "params": {"type": "object"},
                    "timeout": {"type": "number"},
                },
                "required": ["script_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_inline_python",
            "description": "执行简短 Python 片段（params 变量可用）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "params": {"type": "object"},
                    "timeout": {"type": "number"},
                },
                "required": ["code"],
            },
        },
    },
]


def dispatch_tool(name: str, arguments: dict) -> dict:
    """Local Function Calling dispatcher."""
    args = arguments or {}
    if name == "list_files":
        ext = args.get("ext") or ""
        exts = [e.strip() for e in str(ext).replace(" ", "").split(",") if e.strip()] or None
        return {"ok": True, "files": filesystem.list_files(args["root"], exts, int(args.get("limit") or 200))}
    if name == "search_files":
        ext = args.get("ext") or ""
        exts = [e.strip() for e in str(ext).replace(" ", "").split(",") if e.strip()] or None
        files = filesystem.search_files(
            root=args.get("root") or "",
            query=args.get("query") or "*",
            exts=exts,
            content=bool(args.get("content")),
            limit=int(args.get("limit") or 20),
        )
        return {"ok": True, "files": files, "count": len(files)}
    if name == "read_file_meta":
        return filesystem.read_file_meta(args["path"])
    if name == "read_table":
        try:
            df = spreadsheet.load_table(args["path"])
            return {
                "ok": True,
                "rows": int(df.shape[0]),
                "cols": int(df.shape[1]),
                "columns": list(map(str, df.columns)),
                "preview": spreadsheet.preview_table(df, int(args.get("head") or 5)),
            }
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
    if name == "describe_table":
        try:
            df = spreadsheet.load_table(args["path"])
            return {"ok": True, "path": args["path"], **spreadsheet.describe_table(df)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
    if name == "group_by_table":
        try:
            df = spreadsheet.load_table(args["path"])
            return {
                "ok": True,
                "group_result": spreadsheet.group_by_table(
                    df,
                    args["group_by"],
                    args.get("agg_col"),
                    str(args.get("agg_func") or "sum"),
                ),
            }
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
    if name == "search_web":
        try:
            from tools.search import search_web
            hits = search_web(
                args["query"],
                max_results=int(args.get("max_results") or 5),
                timeout=float(args.get("timeout") or 10),
            )
            return {"ok": True, "results": hits, "degraded": False}
        except Exception as e:  # noqa: BLE001
            kb = search.search_knowledge_base(args.get("query") or "", limit=int(args.get("max_results") or 5))
            return {
                "ok": True,
                "results": kb,
                "degraded": True,
                "fallback": {"source": "knowledge_base", "error": str(e)},
            }
    if name == "search_knowledge_base":
        return {
            "ok": True,
            "results": search.search_knowledge_base(args["query"], int(args.get("limit") or 5)),
        }
    if name == "write_file":
        path = document.write_text_file(args["directory"], args["filename"], args["content"])
        return {"ok": True, "path": str(path)}
    if name == "run_python_script":
        return python_runner.run_python_script(
            args["script_path"],
            args.get("params"),
            float(args.get("timeout") or 30),
        )
    if name == "run_inline_python":
        return python_runner.run_inline_python(
            args["code"],
            args.get("params"),
            float(args.get("timeout") or 20),
        )
    return {"ok": False, "error": f"unknown tool: {name}"}
