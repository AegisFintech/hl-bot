import json
import os
import time
from pathlib import Path

from src.agent.guardrails import TUNING_LIMITS, validate_tuning_param, validate_tuning_pair

TUNING_FILE = Path("/root/hl-bot/data/tuning.json")


def read_tuning() -> dict:
    if not TUNING_FILE.exists():
        return {}
    try:
        return json.loads(TUNING_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def write_tuning(updates: dict) -> tuple[bool, str]:
    errors = []
    for k, v in updates.items():
        if k.startswith("_"):
            continue
        ok, msg = validate_tuning_param(k, v)
        if not ok:
            errors.append(msg)
    if errors:
        return False, "; ".join(errors)

    current = read_tuning()
    merged = {k: v for k, v in current.items() if not k.startswith("_")}
    merged.update(updates)

    ok, msg = validate_tuning_pair(merged)
    if not ok:
        return False, msg

    merged["_last_modified"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    tmp = TUNING_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, indent=2))
    os.replace(tmp, TUNING_FILE)
    return True, f"Updated: {list(updates.keys())}"


def get_effective_value(name: str, config_default):
    tuning = read_tuning()
    return tuning.get(name, config_default)
