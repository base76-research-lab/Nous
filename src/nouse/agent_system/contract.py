"""Agent contract — the machine-readable half of an AGENT.md card.

Folders over agents: an agent is a directory with an AGENT.md whose
YAML frontmatter describes it. This module only parses that shape; it
does not hardcode any specific agent's identity or behavior.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class AgentContract:
    id: str
    name: str
    function: str
    role: str
    match: list[str]
    executor: str
    works_when: str
    works_where: str
    input_files: list[str]
    output_file: str
    brief: str
    method: list[str]
    forbidden: list[str]
    quality_bar: list[str]
    stop_condition: str
    source_dir: Path
    executor_options: dict = field(default_factory=dict)
    executor_fallback: str = ""

    @property
    def agent_dir_name(self) -> str:
        return self.source_dir.name


def _split_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        raise ValueError("AGENT.md must start with a --- YAML frontmatter block")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("AGENT.md frontmatter block is not terminated with ---")
    data = yaml.safe_load(parts[1]) or {}
    if not isinstance(data, dict):
        raise ValueError("AGENT.md frontmatter must be a YAML mapping")
    return data


def load_agent_contract(agent_md_path: Path) -> AgentContract:
    text = agent_md_path.read_text(encoding="utf-8")
    data = _split_frontmatter(text)
    return AgentContract(
        id=str(data.get("id", "")),
        name=str(data.get("name", "")),
        function=str(data.get("function", "")),
        role=str(data.get("role", "")).strip(),
        match=list(data.get("match", []) or []),
        executor=str(data.get("executor", "")),
        executor_options=dict(data.get("executor_options", {}) or {}),
        executor_fallback=str(data.get("executor_fallback", "")),
        works_when=str(data.get("works_when", "")).strip(),
        works_where=str(data.get("works_where", "")).strip(),
        input_files=list(data.get("input_files", []) or []),
        output_file=str(data.get("output_file", "")),
        brief=str(data.get("brief", "")).strip(),
        method=list(data.get("method", []) or []),
        forbidden=list(data.get("forbidden", []) or []),
        quality_bar=list(data.get("quality_bar", []) or []),
        stop_condition=str(data.get("stop_condition", "")).strip(),
        source_dir=agent_md_path.parent,
    )
