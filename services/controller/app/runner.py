"""Zagon enega agenta s Claude Agent SDK.
F0: teče znotraj controllerja. F1/F2: vsak zagon v svojem efemernem containerju."""
import datetime as dt
import os
from pathlib import Path

import yaml
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

AGENTS_DIR = Path(os.environ.get("AGENTS_DIR", "/agents"))


def load_agent(name: str) -> dict:
    return yaml.safe_load((AGENTS_DIR / name / "agent.yaml").read_text())


async def run_agent(name: str, run_id: int, extra: str = "") -> dict:
    cfg = load_agent(name)
    agent_dir = AGENTS_DIR / name

    options = ClaudeAgentOptions(
        cwd=str(agent_dir),
        setting_sources=["project"],          # naloži CLAUDE.md iz mape agenta
        model=cfg["models"]["execute"],
        max_turns=cfg["limits"]["max_turns"],
        mcp_servers={
            "executor": {
                "type": "http",
                "url": os.environ["EXECUTOR_MCP_URL"],
                "headers": {"Authorization": f"Bearer {os.environ['EXECUTOR_TOKEN']}"},
            }
        },
        # Agent sme brati svojo mapo in klicati orodja prek Executorja. Nič drugega.
        allowed_tools=["Read", "Glob", "Grep", "mcp__executor__*"],
        disallowed_tools=["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch"],
    )

    today = dt.date.today().isoformat()
    prompt = (f"Run ID: {run_id}. Današnji datum: {today}.\n\n"
              f"Naloga: {cfg['task']}\n")
    if extra:
        prompt += f"\nDodatno navodilo uporabnika: {extra}\n"

    result = {"text": "", "cost_usd": None, "is_error": False}
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, ResultMessage):
            result["text"] = msg.result or ""
            result["cost_usd"] = msg.total_cost_usd
            result["is_error"] = bool(msg.is_error)
    return result
