import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from anthropic import Anthropic

from src.agent.system_prompt import build_system_prompt
from src.agent.tools import (
    get_bot_status, get_performance, get_bot_logs, get_sr_levels,
    update_tuning, edit_source_file, restart_bot, read_source_file,
    reset_run_limits,
)
from src.agent.audit import append_audit

LOG_FILE = Path("/root/hl-bot/data/agent.log")
MODEL = "claude-sonnet-5"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("agent")

TOOLS = [
    get_bot_status,
    get_performance,
    get_bot_logs,
    get_sr_levels,
    update_tuning,
    read_source_file,
    edit_source_file,
    restart_bot,
]

INITIAL_MESSAGE = (
    "Run your regular 15-minute oversight check. Start by getting the bot status "
    "and recent performance. Diagnose any issues, check logs if something looks wrong, "
    "and take corrective action if needed. Summarize your findings at the end."
)


def run_agent():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("ANTHROPIC_API_KEY not set — cannot run agent")
        return

    reset_run_limits()

    client = Anthropic(api_key=api_key)
    system_prompt = build_system_prompt()

    log.info("Starting agent run with model=%s", MODEL)
    start = time.time()

    try:
        result = client.beta.messages.tool_runner(
            model=MODEL,
            system=system_prompt,
            messages=[{"role": "user", "content": INITIAL_MESSAGE}],
            tools=TOOLS,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            max_iterations=15,
        )
    except Exception as e:
        log.error("Agent run failed: %s", e, exc_info=True)
        append_audit({
            "action": "agent_run",
            "result": "error",
            "error": str(e),
        })
        return

    elapsed = time.time() - start

    final_text = ""
    for block in result.content:
        if hasattr(block, "text"):
            final_text += block.text

    usage = {
        "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens,
    }

    log.info("Agent run complete in %.1fs — usage: %s", elapsed, usage)
    log.info("Agent summary:\n%s", final_text[:2000])

    append_audit({
        "action": "agent_run",
        "result": "success",
        "elapsed_s": round(elapsed, 1),
        "usage": usage,
        "summary": final_text[:500],
    })


if __name__ == "__main__":
    run_agent()
