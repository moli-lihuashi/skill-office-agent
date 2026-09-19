"""LLM text generation helpers shared by skills (optional polish path)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def resolve_llm_config(params: dict | None = None) -> dict[str, Any]:
    """Priority: params.llm > env vars > config.json."""
    params = params or {}
    payload = params.get("llm") if isinstance(params.get("llm"), dict) else {}
    cfg_path = ROOT / "config.json"
    file_llm: dict[str, Any] = {}
    if cfg_path.exists():
        try:
            file_llm = (json.loads(cfg_path.read_text(encoding="utf-8")).get("llm") or {})
        except Exception:  # noqa: BLE001
            file_llm = {}
    base_url = os.environ.get("LLM_BASE_URL") or payload.get("base_url") or file_llm.get("base_url") or ""
    api_key = os.environ.get("LLM_API_KEY") or payload.get("api_key") or file_llm.get("api_key") or ""
    model = os.environ.get("LLM_MODEL") or payload.get("model") or file_llm.get("model") or ""
    timeout = payload.get("timeout") or file_llm.get("timeout") or 40
    polish = params.get("llm_polish")
    if polish is None:
        polish = file_llm.get("polish", True)
    return {
        "base_url": str(base_url or "").rstrip("/"),
        "api_key": str(api_key or ""),
        "model": str(model or ""),
        "timeout": float(timeout or 40),
        "polish": bool(polish),
    }


def llm_available(cfg: dict | None = None) -> bool:
    cfg = cfg or resolve_llm_config()
    return bool(cfg.get("base_url") and cfg.get("model"))


def generate_with_llm(
    system: str,
    user: str,
    llm_cfg: dict | None = None,
    temperature: float = 0.3,
) -> tuple[str | None, str | None]:
    """Return (text, error). Never raises — callers fall back to templates."""
    cfg = llm_cfg or resolve_llm_config()
    if not (cfg.get("base_url") and cfg.get("model")):
        return None, "llm_not_configured"
    try:
        from agent.llm import LLMClient
        client = LLMClient.from_payload(cfg)
        text = client.generate_text(system, user, temperature=temperature)
        if not text:
            return None, "llm_empty_response"
        return text, None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def polish_report(
    title: str,
    template_text: str,
    context_payload: Any,
    llm_cfg: dict | None = None,
) -> tuple[str | None, str | None]:
    """Return polished markdown or (None, error)."""
    system = (
        "你是资深办公文秘，擅长把结构化数据写成清晰的中文 Markdown 报告。"
        "只输出报告正文（以 # 标题开始），不要解释过程，不要编造数据中不存在的数字。"
    )
    user = (
        f"报告标题：{title}\n"
        f"上游结构化数据：\n{json.dumps(context_payload, ensure_ascii=False, default=str)[:6000]}\n\n"
        f"模板初稿（可参考结构，可改写，但数字必须与上游一致）：\n{template_text[:4000]}\n\n"
        "请输出完整 Markdown 报告。"
    )
    return generate_with_llm(system, user, llm_cfg)


def polish_email(
    to: str,
    subject: str,
    tone: str,
    points: list[str],
    context_payload: Any,
    template_text: str,
    llm_cfg: dict | None = None,
) -> tuple[str | None, str | None]:
    system = (
        "你是办公邮件撰写助手。根据要点写一封专业、简洁的中文工作邮件。"
        "保留收件人/主题行；只输出邮件全文，不要附加说明。数字必须准确。"
    )
    points_txt = "\n".join(f"{i}. {p}" for i, p in enumerate(points, 1))
    user = (
        f"收件人：{to}\n主题：{subject}\n语气：{tone}\n"
        f"要点：\n{points_txt}\n"
        f"上游数据摘要：\n{json.dumps(context_payload, ensure_ascii=False, default=str)[:4000]}\n"
        f"模板初稿：\n{template_text[:2500]}\n"
        "请输出完整邮件正文。"
    )
    return generate_with_llm(system, user, llm_cfg)
