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
                 max_daily_trades: int = 20, order_size_usd: float = 100):
        self.max_position_size_usd = max_position_size_usd
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.max_open_positions = max_open_positions
        self.max_daily_trades = max_daily_trades
        self.order_size_usd = order_size_usd
        self.state = RiskState()
        self._orders = []
        self._last_order_time: float = 0.0
        self._order_cooldown: float = 60.0
        self._last_block_log: float = 0.0
        self._block_log_interval: float = 300.0

    def update_equity(self, equity: float):
        if equity <= 0:
            return
        if self.state.current_equity > 0 and equity < self.state.current_equity * 0.1:
            log.warning("Equity update rejected (likely API glitch): $%.2f vs current $%.2f",
                        equity, self.state.current_equity)
            return
        self.state.current_equity = equity
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity

    def reset_daily(self):
        self.state.daily_pnl = 0.0
        self.state.daily_trades = 0
        self.state.day_start = time.time()

    def check_daily_reset(self):
        if time.time() - self.state.day_start > 86400:
            log.info("Daily reset — PnL: $%.4f, trades: %d",
                     self.state.daily_pnl, self.state.daily_trades)
            self.state.peak_equity = self.state.current_equity
            self.reset_daily()

    def can_trade(self, signal) -> bool:
        now = time.time()

        if self.state.open_positions >= self.max_open_positions:
            self._log_block_throttled("Max open positions (%d)", self.max_open_positions)
            return False

        if now - self._last_order_time < self._order_cooldown:
            return False

        if self.state.daily_trades >= self.max_daily_trades:
            self._log_block_throttled("Max daily trades (%d)", self.max_daily_trades)
            return False

        if self.state.current_equity > 0:
            daily_loss_limit = self.state.current_equity * self.max_daily_loss_pct
            if self.state.daily_pnl < -daily_loss_limit:
                self._log_block_throttled("Daily loss limit hit ($%.2f)", self.state.daily_pnl)
                return False

        if self.state.drawdown_pct > self.max_drawdown_pct:
            self._log_block_throttled("Max drawdown exceeded (%.1f%%)", self.state.drawdown_pct * 100)
            return False

        return True

    def _log_block_throttled(self, msg: str, *args):
        now = time.time()
        if now - self._last_block_log > self._block_log_interval:
            log.warning(msg, *args)
            self._last_block_log = now

    def compute_position_size(self, signal) -> float:
        size_usd = min(self.order_size_usd, self.max_position_size_usd)

        if self.state.current_equity > 0:
            max_from_equity = self.state.current_equity * 0.1
            size_usd = min(size_usd, max_from_equity)

        if signal.entry_price <= 0:
            return 0.0

        return size_usd / signal.entry_price

    def sync_open_positions(self, count: int):
        if count != self.state.open_positions:
            log.warning("Syncing open_positions: %d -> %d (from exchange)",
                        self.state.open_positions, count)
        self.state.open_positions = count

    def record_order(self, signal, size: float):
        self.state.daily_trades += 1
        self._last_order_time = time.time()
        self._orders.append({
            "signal": signal.to_dict(),
            "size": size,
            "timestamp": self._last_order_time,
        })

    def record_fill(self, pnl: float):
        self.state.daily_pnl += pnl
        if self.state.open_positions > 0:
            self.state.open_positions -= 1

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
