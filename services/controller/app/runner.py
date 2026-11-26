"""Run a single agent with the Claude Agent SDK.
F0: runs inside the controller. F1/F2: each run in its own ephemeral container."""
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
        setting_sources=["project"],          # loads CLAUDE.md from the agent directory
        model=cfg["models"]["execute"],
        max_turns=cfg["limits"]["max_turns"],
        mcp_servers={
            "executor": {
                "type": "http",
                "url": os.environ["EXECUTOR_MCP_URL"],
                "headers": {"Authorization": f"Bearer {os.environ['EXECUTOR_TOKEN']}"},
            }
        },
        # The agent may read its own directory and call tools via Executor. Nothing else.
        allowed_tools=["Read", "Glob", "Grep", "mcp__executor__*"],
        disallowed_tools=["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch"],
    )

    today = dt.date.today().isoformat()
    prompt = (f"Run ID: {run_id}. Today's date: {today}.\n\n"
              f"Task: {cfg['task']}\n")
    if extra:
        prompt += f"\nAdditional user instructions: {extra}\n"

    result = {"text": "", "cost_usd": None, "is_error": False}
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, ResultMessage):
            result["text"] = msg.result or ""
            result["cost_usd"] = msg.total_cost_usd
            result["is_error"] = bool(msg.is_error)
    return result
