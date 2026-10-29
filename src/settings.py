"""Runtime trading settings from environment variables (see .env.example)."""

import json
import os
from dataclasses import asdict, dataclass, field


def _env(name, default, cast=str):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return cast(raw.strip())


def _pct(name, default):
    return _env(name, default * 100, float) / 100


@dataclass
class Settings:
    coins: list = field(default_factory=lambda: ["BTC", "ETH", "SOL"])
    strategy: str = "donchian"
    strategy_params: dict = field(default_factory=dict)
    interval: str = "1h"
    risk_per_trade: float = 0.005
    max_leverage: float = 3.0
    max_gross_leverage: float = 5.0
    max_positions: int = 3
    drawdown_limit: float = 0.05
    cooldown_hours: float = 12.0
    auto_reset: bool = True
    daily_loss_limit: float = 0.0
    max_daily_entries: int = 30
    entry_slippage: float = 0.003
    stop_slippage: float = 0.03
    exchange_leverage: int = 10
    dashboard_port: int = 8080

    @classmethod
    def from_env(cls):
        base = cls()
        coins = [c.strip().upper() for c in _env("TRADE_COINS", ",".join(base.coins)).split(",") if c.strip()]
        return cls(
            coins=coins or base.coins,
            strategy=_env("STRATEGY", base.strategy),
            strategy_params=json.loads(_env("STRATEGY_PARAMS", "{}")),
            interval=_env("STRATEGY_INTERVAL", base.interval),
            risk_per_trade=_pct("RISK_PER_TRADE_PCT", base.risk_per_trade),
            max_leverage=_env("MAX_LEVERAGE_PER_POSITION", base.max_leverage, float),
            max_gross_leverage=_env("MAX_GROSS_LEVERAGE", base.max_gross_leverage, float),
            max_positions=_env("MAX_POSITIONS", base.max_positions, int),
            drawdown_limit=_pct("DRAWDOWN_LIMIT_PCT", base.drawdown_limit),
            cooldown_hours=_env("BREAKER_COOLDOWN_HOURS", base.cooldown_hours, float),
            auto_reset=_env("BREAKER_AUTO_RESET", "true").lower() == "true",
            daily_loss_limit=_pct("DAILY_LOSS_LIMIT_PCT", base.daily_loss_limit),
            max_daily_entries=_env("MAX_DAILY_ENTRIES", base.max_daily_entries, int),
            entry_slippage=_pct("ENTRY_SLIPPAGE_PCT", base.entry_slippage),
            stop_slippage=_pct("STOP_SLIPPAGE_PCT", base.stop_slippage),
            exchange_leverage=_env("EXCHANGE_LEVERAGE", base.exchange_leverage, int),
            dashboard_port=_env("DASHBOARD_PORT", base.dashboard_port, int),
        )

    def validate(self):
        problems = []
        if not self.coins:
            problems.append("TRADE_COINS is empty")
        if not 0 < self.risk_per_trade <= 0.02:
            problems.append("RISK_PER_TRADE_PCT must be in (0, 2]")
        if not 0 < self.drawdown_limit < 1:
            problems.append("DRAWDOWN_LIMIT_PCT must be in (0, 100)")
        if self.max_positions < 1:
            problems.append("MAX_POSITIONS must be at least 1")
        if self.interval not in ("15m", "1h", "4h", "1d"):
            problems.append("STRATEGY_INTERVAL must be one of 15m, 1h, 4h, 1d")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def to_dict(self):
        return asdict(self)
