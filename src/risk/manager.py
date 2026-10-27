"""Durable account risk controls. Percentages are fractions internally."""
import json
import logging
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

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
    day_start_equity: float = 0.0
    equity_updated_at: float = 0.0
    halted: bool = False
    halt_reason: str = ''
    execution_paused: bool = False
    pause_reason: str = ''
    pause_until: float = 0.0
    recovery_count: int = 0

    @property
    def drawdown_pct(self):
        return max(0.0, 1 - self.current_equity / self.peak_equity) if self.peak_equity > 0 else 0.0

class RiskManager:
    def __init__(self, max_position_size_usd=100, max_daily_loss_pct=0.02,
                 max_drawdown_pct=0.05, max_open_positions=1, max_daily_trades=30,
                 order_size_usd=100, state_file=None, risk_per_trade=0.0025):
        self.max_position_size_usd = max_position_size_usd
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = min(max_drawdown_pct, 0.05)
        self.max_open_positions = max_open_positions
        self.max_daily_trades = max_daily_trades
        self.order_size_usd = order_size_usd
        self.risk_per_trade = min(risk_per_trade, 0.0025)
        self.state_file = Path(state_file) if state_file else None
        self._lock = RLock()
        self.state = RiskState(day_start=time.time())
        self._last_order_time = 0.0
        self._order_cooldown = 60.0
        self._last_block_log = 0.0
        if self.state_file and self.state_file.exists():
            try:
                self.state = RiskState(**json.loads(self.state_file.read_text()))
            except Exception:
                self.state.halted = True
                self.state.halt_reason = 'Risk state unreadable; operator review required'
                log.exception('Risk state unreadable: refusing new entries')

    def _save(self):
        if self.state_file:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temp = self.state_file.with_suffix('.tmp')
            temp.write_text(json.dumps(asdict(self.state), indent=2))
            temp.replace(self.state_file)

    def halt(self, reason):
        with self._lock:
            self.state.halted = True
            self.state.halt_reason = reason
            self._save()

    def pause_execution(self, reason):
        """Operational circuit breaker; never clears a durable risk halt."""
        with self._lock:
            self.state.execution_paused = True
            self.state.pause_reason = reason
            self.state.recovery_count += 1
            self.state.pause_until = time.time() + min(1800, 60 * 2 ** min(self.state.recovery_count - 1, 5))
            self._save()
            log.error("Execution paused: %s; recovery delay %.0fs", reason, self.state.pause_until - time.time())

    def resume_execution(self):
        """Caller must verify flat/no orders and sustained fresh account/feed reads."""
        with self._lock:
            if (self.state.halted or not self.state.execution_paused
                    or time.time() < self.state.pause_until
                    or time.time() - self.state.equity_updated_at > 10
                    or self.state.current_equity <= 0
                    or self.state.drawdown_pct >= self.max_drawdown_pct):
                return False
            self.state.execution_paused = False
            self.state.pause_reason = ''
            self._save()
            log.warning("Operational recovery verified; execution resumed; peak and risk halt preserved")
            return True

    def review_legacy_protection_halt(self):
        """Explicit operator-reviewed migration, never called at startup or midnight."""
        with self._lock:
            if (not self.state.halted or self.state.halt_reason != 'Protective order recovery failed'
                    or self.state.drawdown_pct >= self.max_drawdown_pct
                    or time.time() - self.state.equity_updated_at > 10
                    or self.state.current_equity <= 0):
                raise ValueError('Legacy halt is not eligible for reviewed operational recovery')
            self.pause_execution('Reviewed testnet upgrade rejection; verifying recovery')
            self.state.halted = False
            self.state.halt_reason = ''
            self._save()
            log.warning('Operator reviewed legacy protective-order halt; migrated to operational pause')

    def update_equity(self, equity):
        with self._lock:
            if not math.isfinite(equity) or equity < 0:
                raise ValueError('Invalid account equity')
            self.state.current_equity = equity
            self.state.equity_updated_at = time.time()
            self.state.peak_equity = max(self.state.peak_equity, equity)
            if not self.state.day_start_equity:
                self.state.day_start_equity = equity
            if self.state.drawdown_pct + 1e-12 >= self.max_drawdown_pct:
                self.state.halted = True
                self.state.halt_reason = '5% equity high-water drawdown limit'
            self._save()

    def reset_daily(self):
        with self._lock:
            self.state.daily_pnl = 0.0
            self.state.daily_trades = 0
            self.state.day_start = time.time()
            self.state.day_start_equity = self.state.current_equity
            self._save()

    def check_daily_reset(self):
        if datetime.now(timezone.utc).date() > datetime.fromtimestamp(self.state.day_start, timezone.utc).date():
            self.reset_daily()  # Never reset peak or a latched halt.

    def can_trade(self, signal):
        s = self.state
        if s.halted or s.execution_paused or s.current_equity <= 0 or time.time() - s.equity_updated_at > 30:
            return False
        if s.open_positions >= self.max_open_positions or s.open_order_count > 0:
            return False
        if time.time() - self._last_order_time < self._order_cooldown or s.daily_trades >= self.max_daily_trades:
            return False
        if s.day_start_equity and s.current_equity <= s.day_start_equity * (1 - self.max_daily_loss_pct):
            return False
        if s.daily_pnl <= -s.day_start_equity * self.max_daily_loss_pct:
            return False
        return s.drawdown_pct < self.max_drawdown_pct

    def compute_position_size(self, signal):
        entry = signal.entry_price
        distance = abs(entry - signal.sl_price)
        if entry <= 0 or distance <= 0 or self.state.current_equity <= 0:
            return 0.0
        # Budget for stop distance plus conservative fees/slippage (12bps round trip).
        budget = self.state.current_equity * self.risk_per_trade
        remaining = max(0, self.state.current_equity - self.state.peak_equity * (1 - self.max_drawdown_pct))
        budget = min(budget, remaining * 0.25)
        notional = min(self.order_size_usd, self.max_position_size_usd, self.state.current_equity * 0.2,
                       budget / (distance / entry + 0.0012))
        return max(0.0, notional / entry)

    def sync_open_positions(self, count):
        self.state.open_positions = count

    def record_order(self, signal, size):
        with self._lock:
            self.state.daily_trades += 1
            self._last_order_time = time.time()
            self._save()

    def record_fill(self, pnl):
        with self._lock:
            self.state.daily_pnl += pnl
            self._save()

    def should_kill(self):
        return self.state.halted or self.state.execution_paused

    def get_state_dict(self):
        with self._lock:
            d = asdict(self.state)
            d.update(drawdown_pct=round(self.state.drawdown_pct * 100, 4),
                     max_drawdown_pct=self.max_drawdown_pct * 100,
                     risk_per_trade_pct=self.risk_per_trade * 100,
                     equity_age_s=round(time.time() - self.state.equity_updated_at, 1),
                     drawdown_budget_usd=max(0, self.state.current_equity - self.state.peak_equity * (1-self.max_drawdown_pct)))
            return d
