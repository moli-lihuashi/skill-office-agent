"""Optional OpenAI-compatible LLM client for reasoning / function calling."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from tools import FUNCTION_CALLING_TOOLS, dispatch_tool


class LLMClient:
    def __init__(self, base_url: str = "", api_key: str = "", model: str = "", timeout: float = 40):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.model)

    def config_payload(self) -> dict[str, Any]:
        """Serializable config for skill subprocesses (no server-side secret store yet)."""
        return {
            "base_url": self.base_url,
            "api_key": self.api_key,
            "model": self.model,
            "timeout": self.timeout,
        }

    @classmethod
    def from_payload(cls, payload: dict | None) -> "LLMClient":
        payload = payload or {}
        return cls(
            base_url=str(payload.get("base_url") or ""),
            api_key=str(payload.get("api_key") or ""),
            model=str(payload.get("model") or ""),
            timeout=float(payload.get("timeout") or 40),
        )

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.2,
        tool_choice: Any | None = None,
    ) -> dict:
        if not self.available:
            raise RuntimeError("LLM not configured")
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            if tool_choice is not None:
                body["tool_choice"] = tool_choice
        url = self.base_url + "/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def generate_text(self, system: str, user: str, temperature: float = 0.3) -> str:
        """Plain chat completion for document polish / final text generation."""
        data = self.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            tools=None,
            temperature=temperature,
        )
        msg = data["choices"][0]["message"]
        return (msg.get("content") or "").strip()

    def run_function_calling_loop(
        self,
        system: str,
        user: str,
        max_rounds: int = 4,
        tools: list[dict] | None = None,
    ) -> dict:
        """Classic function-calling agent loop.

        Returns:
            {
              "ok": bool,
              "answer": str,
              "tool_calls": [{"name","arguments","result"}, ...],
              "rounds": int,
              "error": str | None,
            }
        """
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        tool_catalog = tools if tools is not None else FUNCTION_CALLING_TOOLS
        tool_calls_log: list[dict] = []
        last_err = None
        rounds = 0
        try:
            for rounds in range(1, max_rounds + 1):
                data = self.chat(messages, tools=tool_catalog, temperature=0.1)
                msg = data["choices"][0]["message"]
                messages.append(msg)
                calls = msg.get("tool_calls") or []
                if not calls:
                    return {
                        "ok": True,
                        "answer": msg.get("content") or "",
                        "tool_calls": tool_calls_log,
                        "rounds": rounds,
                        "error": None,
                    }
                for tc in calls:
                    fn = tc.get("function") or {}
                    name = fn.get("name")
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    try:
                        tool_result = dispatch_tool(name, args)
                    except Exception as e:  # noqa: BLE001
                        tool_result = {"ok": False, "error": str(e)}
                    tool_calls_log.append({
                        "name": name,
                        "arguments": args,
                        "result": tool_result,
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id") or name,
                        "name": name,
                        "content": json.dumps(tool_result, ensure_ascii=False, default=str)[:12000],
                    })
            return {
                "ok": bool(tool_calls_log),
                "answer": "已达最大工具调用轮次，请基于已收集工具结果作答。",
                "tool_calls": tool_calls_log,
                "rounds": rounds,
                "error": "max_rounds_exceeded",
            }
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            return {
                "ok": False,
                "answer": "",
                "tool_calls": tool_calls_log,
                "rounds": rounds,
                "error": last_err,
            }
