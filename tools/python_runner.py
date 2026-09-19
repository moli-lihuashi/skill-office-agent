"""Python script runner tool for Function Calling (subprocess isolation)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_python_script(
    script_path: str,
    params: dict | None = None,
    timeout: float = 30,
    python_exe: str | None = None,
) -> dict:
    """Run a skill script with JSON params on stdin; capture JSON on stdout."""
    script = Path(script_path)
    if not script.exists():
        return {"ok": False, "error": f"script not found: {script_path}"}

    exe = python_exe or sys.executable
    payload = json.dumps(params or {}, ensure_ascii=False)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        proc = subprocess.run(
            [exe, "-u", str(script)],
            input=payload.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            cwd=str(ROOT),
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"timeout after {timeout}s",
            "error_type": "timeout",
            "stdout": "",
            "stderr": "",
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "error_type": type(e).__name__}

    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": f"exit={proc.returncode}: {stderr[-1000:]}",
            "error_type": "script_error",
            "stdout": stdout[-2000:],
            "stderr": stderr[-2000:],
        }

    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            data.setdefault("ok", True)
            return data
        return {"ok": True, "data": data}
    except json.JSONDecodeError:
        return {"ok": True, "raw": stdout, "warnings": ["script stdout is not JSON"]}


def run_inline_python(code: str, params: dict | None = None, timeout: float = 20) -> dict:
    """Execute a short inline snippet; params available as `params` dict."""
    wrapper = (
        "import json,sys\n"
        "params=json.loads(sys.stdin.read() or '{}')\n"
        "result=None\n"
        f"{code}\n"
        "print(json.dumps(result, ensure_ascii=False, default=str))\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix="_agent_snippet.py", delete=False, encoding="utf-8") as f:
        f.write(wrapper)
        path = f.name
    try:
        return run_python_script(path, params or {}, timeout=timeout)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
