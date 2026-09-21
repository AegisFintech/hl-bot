from pathlib import Path

PROJECT_ROOT = Path("/root/hl-bot")

TUNING_LIMITS = {
    "tp_pips":          (50, 500),
    "sl_pips":          (20, 200),
    "order_size_usd":   (10, 500),
    "proximity_pct":    (0.001, 0.01),
    "sr_lookback":      (100, 2000),
    "min_touches":      (1, 5),
    "signal_cooldown":  (30.0, 600.0),
}

FORBIDDEN_PATHS = {".env", ".env.example"}
FORBIDDEN_PREFIXES = ("src/agent/", ".git/", "data/agent_audit.json")

MAX_RESTARTS_PER_RUN = 2
MAX_EDITS_PER_RUN = 3
MAX_LOG_LINES = 500


def validate_tuning_param(name: str, value) -> tuple[bool, str]:
    if name not in TUNING_LIMITS:
        return False, f"Unknown parameter: {name}"
    lo, hi = TUNING_LIMITS[name]
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False, f"{name}: not a number"
    if v < lo or v > hi:
        return False, f"{name}={v} out of range [{lo}, {hi}]"
    return True, "ok"


def validate_tuning_pair(params: dict) -> tuple[bool, str]:
    tp = params.get("tp_pips")
    sl = params.get("sl_pips")
    if tp is not None and sl is not None and float(tp) < float(sl):
        return False, "tp_pips must be >= sl_pips (maintain positive R:R)"
    return True, "ok"


def validate_file_path(path: str) -> tuple[bool, str]:
    if path in FORBIDDEN_PATHS:
        return False, f"Forbidden: {path}"
    for prefix in FORBIDDEN_PREFIXES:
        if path.startswith(prefix):
            return False, f"Forbidden prefix: {prefix}"
    full = PROJECT_ROOT / path
    if not full.resolve().is_relative_to(PROJECT_ROOT):
        return False, "Path escapes project root"
    if not full.suffix == ".py":
        return False, "Only .py files can be edited"
    return True, "ok"


class RunLimits:
    def __init__(self):
        self.restarts = 0
        self.edits = 0

    def can_restart(self) -> bool:
        return self.restarts < MAX_RESTARTS_PER_RUN

    def can_edit(self) -> bool:
        return self.edits < MAX_EDITS_PER_RUN

    def record_restart(self):
        self.restarts += 1

    def record_edit(self):
        self.edits += 1
