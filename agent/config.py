"""Configuration loading for skill-office-agent."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config.json"


@dataclass
class AgentConfig:
    root: Path = ROOT
    skills_dir: Path = field(default_factory=lambda: ROOT / "skills")
    data_dir: Path = field(default_factory=lambda: ROOT / "data")
    workspace_dir: Path = field(default_factory=lambda: ROOT / "data" / "workspace")
    knowledge_path: Path = field(default_factory=lambda: ROOT / "knowledge" / "office_kb.json")
    templates_dir: Path = field(default_factory=lambda: ROOT / "templates")
    logs_dir: Path = field(default_factory=lambda: ROOT / "logs")

    # fault tolerance
    default_timeout: float = 30.0
    default_retries: int = 2
    backoff_factor: float = 1.5
    router_min_score: float = 2.0
    enable_llm_router: bool = True

    # optional OpenAI-compatible LLM (function calling)
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout: float = 40.0

    # agent mode: rule | llm_agent | hybrid
    agent_mode: str = "hybrid"
    llm_polish: bool = True
    llm_agent_max_rounds: int = 4

    # search
    search_timeout: float = 10.0

    @staticmethod
    def load(path: Path | str | None = None) -> "AgentConfig":
        cfg_path = Path(path) if path else Path(os.environ.get("SKILL_AGENT_CONFIG") or DEFAULT_CONFIG)
        data = {}
        if cfg_path.exists():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg = AgentConfig()
        cfg.root = ROOT
        cfg.skills_dir = ROOT / data.get("skills_dir", "skills")
        cfg.data_dir = ROOT / data.get("data_dir", "data")
        cfg.workspace_dir = ROOT / data.get("workspace_dir", "data/workspace")
        cfg.knowledge_path = ROOT / data.get("knowledge_path", "knowledge/office_kb.json")
        cfg.templates_dir = ROOT / data.get("templates_dir", "templates")
        cfg.logs_dir = ROOT / data.get("logs_dir", "logs")

        fault = data.get("fault_tolerance", {})
        cfg.default_timeout = float(fault.get("default_timeout", 30))
        cfg.default_retries = int(fault.get("retries", 2))
        cfg.backoff_factor = float(fault.get("backoff_factor", 1.5))
        cfg.router_min_score = float(data.get("router", {}).get("min_score", 2.0))
        cfg.enable_llm_router = bool(data.get("router", {}).get("enable_llm", True))

        llm = data.get("llm", {})
        cfg.llm_base_url = os.environ.get("LLM_BASE_URL") or llm.get("base_url", "")
        cfg.llm_api_key = os.environ.get("LLM_API_KEY") or llm.get("api_key", "")
        cfg.llm_model = os.environ.get("LLM_MODEL") or llm.get("model", "")
        cfg.llm_timeout = float(llm.get("timeout", 40))
        cfg.llm_polish = bool(llm.get("polish", True))
        cfg.search_timeout = float(data.get("search", {}).get("timeout", 8))

        agent_cfg = data.get("agent", {})
        cfg.agent_mode = str(os.environ.get("SKILL_AGENT_MODE") or agent_cfg.get("mode") or "hybrid").lower()
        if cfg.agent_mode not in {"rule", "llm_agent", "hybrid"}:
            cfg.agent_mode = "hybrid"
        cfg.llm_agent_max_rounds = int(agent_cfg.get("llm_max_rounds") or 4)
        return cfg
