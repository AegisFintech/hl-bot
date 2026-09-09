import time
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class RiskState:
    daily_pnl: float = 0.0
    daily_trades: int = 0
    open_positions: int = 0
    open_order_count: int = 0
    peak_equity: float = 0.0
    current_equity: float = 0.0
    day_start: float = 0.0

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - self.current_equity) / self.peak_equity


class RiskManager:

    def __init__(self, max_position_size_usd: float = 100, max_daily_loss_pct: float = 0.05,
                 max_drawdown_pct: float = 0.10, max_open_positions: int = 3,
                 max_daily_trades: int = 50, order_size_usd: float = 100):
        self.max_position_size_usd = max_position_size_usd
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.max_open_positions = max_open_positions
        self.max_daily_trades = max_daily_trades
        self.order_size_usd = order_size_usd
        self.state = RiskState()
        self._orders = []

    def update_equity(self, equity: float):
        self.state.current_equity = equity
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity

    def reset_daily(self):
        self.state.daily_pnl = 0.0
        self.state.daily_trades = 0
        self.state.day_start = time.time()

    def can_trade(self, signal) -> bool:
        if self.state.open_positions >= self.max_open_positions:
            log.warning("Max open positions reached (%d)", self.max_open_positions)
            return False

        if self.state.daily_trades >= self.max_daily_trades:
            log.warning("Max daily trades reached (%d)", self.max_daily_trades)
            return False

        if self.state.current_equity > 0:
            daily_loss_limit = self.state.current_equity * self.max_daily_loss_pct
            if self.state.daily_pnl < -daily_loss_limit:
                log.warning("Daily loss limit hit (%.2f)", self.state.daily_pnl)
                return False

        if self.state.drawdown_pct > self.max_drawdown_pct:
            log.warning("Max drawdown exceeded (%.2f%%)", self.state.drawdown_pct * 100)
            return False

        return True

    def compute_position_size(self, signal) -> float:
        size_usd = min(self.order_size_usd, self.max_position_size_usd)

        if self.state.current_equity > 0:
            max_from_equity = self.state.current_equity * 0.1
            size_usd = min(size_usd, max_from_equity)

        if signal.entry_price <= 0:
            return 0.0

        return size_usd / signal.entry_price

    def record_order(self, signal, size: float):
        self.state.open_positions += 1
        self.state.daily_trades += 1
        self._orders.append({
            "signal": signal.to_dict(),
            "size": size,
            "timestamp": time.time(),
        })

    def record_fill(self, pnl: float):
        self.state.daily_pnl += pnl
        self.state.open_positions = max(0, self.state.open_positions - 1)

    def should_kill(self) -> bool:
        if self.state.drawdown_pct > self.max_drawdown_pct * 1.5:
            log.critical("Emergency stop: drawdown %.2f%% exceeds kill threshold",
                         self.state.drawdown_pct * 100)
            return True
        return False

    def get_state_dict(self) -> dict:
        return {
            "daily_pnl": round(self.state.daily_pnl, 4),
            "daily_trades": self.state.daily_trades,
            "open_positions": self.state.open_positions,
            "peak_equity": round(self.state.peak_equity, 2),
            "current_equity": round(self.state.current_equity, 2),
            "drawdown_pct": round(self.state.drawdown_pct * 100, 2),
        }
