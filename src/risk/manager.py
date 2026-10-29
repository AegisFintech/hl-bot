"""Durable account risk controls. Percentages are fractions internally.

Two independent circuit breakers:

* Drawdown breaker (``halted``): equity at or below ``peak * (1 - max_drawdown_pct)``
  flattens the account. When ``cooldown_s`` has elapsed, exposure is confirmed
  flat and equity is fresh, the peak is re-based to current equity and trading
  resumes automatically (operator decision 2026-10-29). Every trip and reset is
  kept in ``events``. Restarts and midnight never clear a breaker early.
* Operational pause (``execution_paused``): an order outcome or protection could
  not be verified. Entries stop, protected positions are kept, and trading resumes
  after the backoff once the bot has made three healthy checks. Escalation decays
  after an hour without incidents.
"""
import json
import logging
import math
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

log = logging.getLogger(__name__)

MAX_EVENTS = 50


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
    halted_at: float = 0.0
    cooldown_until: float = 0.0
    breaker_trips: int = 0
    last_pause_at: float = 0.0
    events: list = field(default_factory=list)

    @property
    def drawdown_pct(self):
        return max(0.0, 1 - self.current_equity / self.peak_equity) if self.peak_equity > 0 else 0.0


def position_size(equity, entry, stop, risk_per_trade, max_leverage, max_gross_leverage,
                  open_notional=0.0, max_notional=None):
    """Units whose stop-out loses ``risk_per_trade`` of equity, within leverage caps.

    Shared by live execution and the backtester so both size identically.
    """
    distance = abs(entry - stop)
    if not all(math.isfinite(v) for v in (equity, entry, stop)) or equity <= 0 or entry <= 0 or distance <= 0:
        return 0.0
    notional = equity * risk_per_trade / distance * entry
    caps = [equity * max_leverage, equity * max_gross_leverage - open_notional]
    if max_notional:
        caps.append(max_notional)
    return max(0.0, min([notional] + caps)) / entry


class RiskManager:
    def __init__(self, max_position_size_usd=0.0, max_daily_loss_pct=0.0,
                 max_drawdown_pct=0.05, max_open_positions=1, max_daily_trades=30,
                 order_size_usd=0.0, state_file=None, risk_per_trade=0.005,
                 cooldown_s=12 * 3600, max_leverage=3.0, max_gross_leverage=5.0, auto_reset=True):
        self.max_position_size_usd = max_position_size_usd
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.max_open_positions = max_open_positions
        self.max_daily_trades = max_daily_trades
        self.order_size_usd = order_size_usd
        self.risk_per_trade = min(risk_per_trade, 0.02)
        self.cooldown_s = cooldown_s
        self.max_leverage = max_leverage
        self.max_gross_leverage = max_gross_leverage
        self.auto_reset = auto_reset
        self.state_file = Path(state_file) if state_file else None
        self._lock = RLock()
        self.state = RiskState(day_start=time.time())
        self._last_order_time = 0.0
        if self.state_file and self.state_file.exists():
            self._load()

    def _load(self):
        try:
            raw = json.loads(self.state_file.read_text())
            known = {f.name for f in fields(RiskState)}
            self.state = RiskState(**{k: v for k, v in raw.items() if k in known})
        except Exception:
            log.exception('Risk state unreadable; preserving it and halting until the cooldown elapses')
            try:
                self.state_file.replace(self.state_file.with_suffix(f'.corrupt-{int(time.time())}'))
            except OSError:
                pass
            self.state = RiskState(day_start=time.time())
            self._trip('Risk state unreadable; previous peak unknown')
            return
        if self.state.halted and not self.state.cooldown_until and self.auto_reset:
            # Halts written before auto-reset existed carry no cooldown and have been in
            # force since their trip; a recorded trip time still gets its full cooldown.
            s = self.state
            s.cooldown_until = s.halted_at + self.cooldown_s if s.halted_at else time.time()
            self._event('legacy_halt_migrated', reason=self.state.halt_reason)
            log.warning('Legacy risk halt "%s" migrated to auto-reset; resumes once flat', self.state.halt_reason)
            self._save()

    def _save(self):
        if self.state_file:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temp = self.state_file.with_suffix('.tmp')
            temp.write_text(json.dumps(asdict(self.state), indent=2))
            temp.replace(self.state_file)

    def _event(self, kind, **detail):
        self.state.events = (self.state.events + [dict(time=time.time(), kind=kind, **detail)])[-MAX_EVENTS:]

    def _trip(self, reason):
        s, now = self.state, time.time()
        s.halted, s.halt_reason, s.halted_at = True, reason, now
        s.cooldown_until = now + self.cooldown_s if self.auto_reset else 0.0
        s.breaker_trips += 1
        self._event('breaker_trip', reason=reason, equity=s.current_equity, peak=s.peak_equity,
                    resume_after=s.cooldown_until)
        log.critical('Risk breaker tripped: %s; flattening, auto-reset after %s', reason,
                     datetime.fromtimestamp(s.cooldown_until, timezone.utc).isoformat() if s.cooldown_until else 'never')
        self._save()

    def halt(self, reason):
        with self._lock:
            self._trip(reason)

    def pause_execution(self, reason):
        """Operational circuit breaker; never clears a drawdown breaker."""
        with self._lock:
            s, now = self.state, time.time()
            if now - s.last_pause_at > 3600:
                s.recovery_count = 0  # Escalation decays after an hour without incidents.
            s.execution_paused = True
            s.pause_reason = reason
            s.recovery_count += 1
            s.last_pause_at = now
            s.pause_until = now + min(1800, 60 * 2 ** min(s.recovery_count - 1, 5))
            self._event('execution_pause', reason=reason, resume_after=s.pause_until)
            self._save()
            log.error("Execution paused: %s; recovery delay %.0fs", reason, s.pause_until - now)

    def resume_execution(self):
        """Caller must verify exposure is protected and account/feed reads are healthy."""
        with self._lock:
            s = self.state
            if (s.halted or not s.execution_paused or time.time() < s.pause_until
                    or time.time() - s.equity_updated_at > 10 or s.current_equity <= 0):
                return False
            s.execution_paused = False
            s.pause_reason = ''
            self._event('execution_resumed')
            self._save()
            log.warning("Operational recovery verified; execution resumed")
            return True

    def try_reset_after_cooldown(self, flat_confirmed):
        """Re-base the peak and resume after a breaker cooldown, once confirmed flat."""
        with self._lock:
            s, now = self.state, time.time()
            if (not s.halted or not self.auto_reset or not s.cooldown_until or now < s.cooldown_until
                    or not flat_confirmed or now - s.equity_updated_at > 10 or s.current_equity <= 0):
                return False
            previous = s.peak_equity
            s.peak_equity = s.current_equity
            s.day_start_equity = s.current_equity
            s.daily_pnl = 0.0
            s.halted, s.halt_reason, s.cooldown_until = False, '', 0.0
            self._event('breaker_reset', previous_peak=previous, new_peak=s.peak_equity)
            self._save()
            log.warning('Breaker cooldown elapsed and account flat: peak re-based %.2f -> %.2f; trading resumes',
                        previous, s.peak_equity)
            return True

    def update_equity(self, equity):
        with self._lock:
            if not math.isfinite(equity) or equity < 0:
                raise ValueError('Invalid account equity')
            s = self.state
            s.current_equity = equity
            s.equity_updated_at = time.time()
            s.peak_equity = max(s.peak_equity, equity)
            if not s.day_start_equity:
                s.day_start_equity = equity
            if not s.halted and s.drawdown_pct + 1e-12 >= self.max_drawdown_pct:
                self._trip(f'{self.max_drawdown_pct:.0%} equity drawdown from peak {s.peak_equity:.2f}')
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
            self.reset_daily()  # Daily counters only; never the peak or a breaker.

    def admission(self):
        """Empty string when new exposure is allowed, otherwise the blocking reason."""
        s, now = self.state, time.time()
        if s.halted:
            return f'Drawdown breaker: {s.halt_reason}'
        if s.execution_paused:
            return f'Execution paused: {s.pause_reason}'
        if s.current_equity <= 0:
            return 'Account equity unavailable'
        if now - s.equity_updated_at > 30:
            return 'Account equity is stale'
        if s.open_positions >= self.max_open_positions:
            return f'Maximum open positions ({self.max_open_positions})'
        if s.daily_trades >= self.max_daily_trades:
            return f'Daily entry limit ({self.max_daily_trades})'
        if (self.max_daily_loss_pct and s.day_start_equity
                and s.current_equity <= s.day_start_equity * (1 - self.max_daily_loss_pct)):
            return f'Daily loss limit ({self.max_daily_loss_pct:.0%})'
        return ''

    def can_trade(self, signal=None):
        return not self.admission()

    def size_for(self, entry, stop, open_notional=0.0):
        return position_size(self.state.current_equity, entry, stop, self.risk_per_trade, self.max_leverage,
                             self.max_gross_leverage, open_notional, self.max_position_size_usd or None)

    def compute_position_size(self, signal):
        return self.size_for(signal.entry_price, signal.sl_price)

    def sync_open_positions(self, count):
        self.state.open_positions = count

    def record_order(self, signal=None, size=None):
        with self._lock:
            self.state.daily_trades += 1
            self._last_order_time = time.time()
            self._save()

    def record_fill(self, pnl):
        with self._lock:
            self.state.daily_pnl += pnl
            self._save()

    def should_flatten(self):
        return self.state.halted

    def should_kill(self):
        """Any breaker that blocks new exposure (kept for existing callers)."""
        return self.state.halted or self.state.execution_paused

    def get_state_dict(self):
        with self._lock:
            s, now = self.state, time.time()
            d = asdict(s)
            d['events'] = s.events[-10:]
            d.update(drawdown_pct=round(s.drawdown_pct * 100, 4),
                     max_drawdown_pct=self.max_drawdown_pct * 100,
                     risk_per_trade_pct=self.risk_per_trade * 100,
                     equity_age_s=round(now - s.equity_updated_at, 1),
                     cooldown_remaining_s=max(0.0, s.cooldown_until - now) if s.halted else 0.0,
                     auto_reset=self.auto_reset, cooldown_hours=self.cooldown_s / 3600,
                     admission=self.admission() or 'Open',
                     drawdown_budget_usd=max(0, s.current_equity - s.peak_equity * (1 - self.max_drawdown_pct)))
            return d
