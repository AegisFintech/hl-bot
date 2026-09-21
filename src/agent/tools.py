import json
import subprocess
import time
from pathlib import Path

import requests
from anthropic import beta_tool

from src.agent.guardrails import (
    RunLimits, validate_file_path, validate_tuning_param, MAX_LOG_LINES,
)
from src.agent.audit import append_audit
from src.agent.tuning import read_tuning, write_tuning

PROJECT_ROOT = Path("/root/hl-bot")
DASHBOARD_BASE = "http://localhost:8080"

_run_limits = RunLimits()


def reset_run_limits():
    global _run_limits
    _run_limits = RunLimits()


def _api_get(path: str) -> dict | list | None:
    try:
        r = requests.get(f"{DASHBOARD_BASE}{path}", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@beta_tool
def get_bot_status() -> str:
    """Get current bot status including positions, orders, equity, and risk state.
    Call this first to understand the current state of the bot."""
    status = _api_get("/api/status")
    positions = _api_get("/api/positions")
    orders = _api_get("/api/orders")
    account = _api_get("/api/account")
    return json.dumps({
        "status": status,
        "positions": positions,
        "orders": orders,
        "account": account,
    }, indent=2)


@beta_tool
def get_performance(last_n_trades: int = 20) -> str:
    """Get trading performance metrics and recent trade history.

    Args:
        last_n_trades: Number of recent trades to include (default 20).
    """
    perf = _api_get("/api/performance")
    trades = _api_get("/api/trades")
    if isinstance(trades, list):
        trades = trades[-last_n_trades:]
    return json.dumps({"performance": perf, "recent_trades": trades}, indent=2)


@beta_tool
def get_bot_logs(lines: int = 200, grep_pattern: str = "") -> str:
    """Read recent bot log entries. Use grep_pattern to filter for specific events.

    Args:
        lines: Number of recent lines to read (max 500).
        grep_pattern: Optional grep filter (e.g. 'ERROR', 'Fill:', 'kill').
    """
    lines = min(lines, MAX_LOG_LINES)
    log_path = PROJECT_ROOT / "bot.log"
    if not log_path.exists():
        return "bot.log not found"
    try:
        all_lines = log_path.read_text().splitlines()
        tail = all_lines[-lines:]
        if grep_pattern:
            tail = [l for l in tail if grep_pattern.lower() in l.lower()]
        return "\n".join(tail) if tail else "(no matching lines)"
    except Exception as e:
        return f"Error reading log: {e}"


@beta_tool
def get_sr_levels() -> str:
    """Get current support/resistance levels and order blocks detected by the bot."""
    data = _api_get("/api/sr_levels")
    return json.dumps(data, indent=2)


@beta_tool
def update_tuning(
    tp_pips: int | None = None,
    sl_pips: int | None = None,
    order_size_usd: float | None = None,
    proximity_pct: float | None = None,
    sr_lookback: int | None = None,
    min_touches: int | None = None,
    signal_cooldown: float | None = None,
) -> str:
    """Update bot trading parameters via hot-reload. Only pass parameters you want to change.
    The bot picks up changes within 60 seconds without restart.

    Args:
        tp_pips: Take-profit in pips (range: 50-500).
        sl_pips: Stop-loss in pips (range: 20-200).
        order_size_usd: Order size in USD (range: 10-500).
        proximity_pct: How close price must be to S/R level (range: 0.001-0.01).
        sr_lookback: Number of candles for S/R detection (range: 100-2000).
        min_touches: Minimum touches for a valid S/R level (range: 1-5).
        signal_cooldown: Seconds between signals on same level (range: 30-600).
    """
    params = {}
    local_vars = {
        "tp_pips": tp_pips, "sl_pips": sl_pips, "order_size_usd": order_size_usd,
        "proximity_pct": proximity_pct, "sr_lookback": sr_lookback,
        "min_touches": min_touches, "signal_cooldown": signal_cooldown,
    }
    for k, v in local_vars.items():
        if v is not None:
            params[k] = v

    if not params:
        return "No parameters provided."

    ok, msg = write_tuning(params)
    if ok:
        append_audit({
            "action": "update_tuning",
            "params": params,
            "result": "success",
        })
    return msg


@beta_tool
def read_source_file(file_path: str) -> str:
    """Read a source code file. Use to understand current logic before making edits.

    Args:
        file_path: Relative path from project root (e.g. 'src/strategy/scalper.py').
    """
    ok, msg = validate_file_path(file_path)
    if not ok:
        return f"Blocked: {msg}"
    full = PROJECT_ROOT / file_path
    if not full.exists():
        return f"File not found: {file_path}"
    try:
        return full.read_text()
    except Exception as e:
        return f"Error reading: {e}"


@beta_tool
def edit_source_file(file_path: str, find_text: str, replace_text: str, reason: str) -> str:
    """Edit a source code file using find-and-replace. The bot must be restarted after code changes.

    Args:
        file_path: Relative path from project root (e.g. 'src/strategy/scalper.py').
        find_text: Exact text to find (must match exactly once).
        replace_text: Text to replace it with.
        reason: Why this change is being made (logged to audit).
    """
    if not _run_limits.can_edit():
        return "Edit limit reached for this run (max 3)."

    ok, msg = validate_file_path(file_path)
    if not ok:
        return f"Blocked: {msg}"

    full = PROJECT_ROOT / file_path
    if not full.exists():
        return f"File not found: {file_path}"

    content = full.read_text()
    count = content.count(find_text)
    if count == 0:
        return "find_text not found in file."
    if count > 1:
        return f"find_text matches {count} times — must be unique. Add more context."

    new_content = content.replace(find_text, replace_text, 1)
    tmp = full.with_suffix(".py.tmp")
    tmp.write_text(new_content)
    tmp.replace(full)

    _run_limits.record_edit()
    append_audit({
        "action": "edit_source_file",
        "file": file_path,
        "reason": reason,
        "find_text_preview": find_text[:100],
        "replace_text_preview": replace_text[:100],
        "result": "success",
    })
    return f"Edited {file_path}. Restart needed for changes to take effect."


@beta_tool
def restart_bot(reason: str) -> str:
    """Restart the hl-bot systemd service. Use after code changes or when the bot is stuck.

    Args:
        reason: Why the restart is needed (logged to audit).
    """
    if not _run_limits.can_restart():
        return "Restart limit reached for this run (max 2)."

    try:
        subprocess.run(["systemctl", "restart", "hl-bot"], check=True, timeout=30)
    except Exception as e:
        return f"Restart failed: {e}"

    time.sleep(10)

    try:
        result = subprocess.run(
            ["systemctl", "is-active", "hl-bot"],
            capture_output=True, text=True, timeout=5,
        )
        active = result.stdout.strip() == "active"
    except Exception:
        active = False

    _run_limits.record_restart()
    status = "running" if active else "NOT running"
    append_audit({
        "action": "restart_bot",
        "reason": reason,
        "result": status,
    })
    return f"Bot restarted. Status: {status}"
