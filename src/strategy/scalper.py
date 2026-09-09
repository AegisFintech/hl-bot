import time
import logging
from dataclasses import dataclass, asdict

from src.exchange.hyperliquid import HyperliquidClient
from src.strategy.sr_detector import SRDetector, SRLevel, OrderBlock
from src.risk.manager import RiskManager

log = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    coin: str
    side: str  # "long" or "short"
    entry_price: float
    tp_price: float
    sl_price: float
    sr_level: float
    sr_kind: str
    sr_strength: float
    ob_zone: tuple | None = None
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return asdict(self)


class Scalper:

    def __init__(self, client: HyperliquidClient, sr_detector: SRDetector,
                 risk_manager: RiskManager, coin: str, tp_pips: int = 5,
                 sl_pips: int = 10, pip_size: float | None = None):
        self.client = client
        self.sr = sr_detector
        self.risk = risk_manager
        self.coin = coin
        self.tp_pips = tp_pips
        self.sl_pips = sl_pips
        self._pip_size = pip_size
        self.active_signals: list[TradeSignal] = []
        self._last_sr_update = 0.0
        self._sr_update_interval = 60.0

    @property
    def pip_size(self) -> float:
        if self._pip_size is not None:
            return self._pip_size
        price = self.client.get_mid_price(self.coin)
        if price > 10000:
            return 1.0
        elif price > 1000:
            return 0.1
        elif price > 100:
            return 0.01
        else:
            return 0.001

    def update_sr_levels(self, candles: list[dict] | None = None):
        if candles is None:
            candles = self.client.get_cached_candles(self.coin)
            if not candles:
                candles = self.client.get_candles(self.coin, "1m", 100 * 60 * 1000)

        self.sr.detect(candles)
        self.sr.detect_order_blocks(candles)
        self._last_sr_update = time.time()
        log.info("Updated S/R levels: %d levels, %d order blocks",
                 len(self.sr._levels), len(self.sr._order_blocks))

    def scan_for_signals(self) -> list[TradeSignal]:
        now = time.time()
        if now - self._last_sr_update > self._sr_update_interval:
            self.update_sr_levels()

        bbo = self.client.get_cached_bbo(self.coin)
        if not bbo:
            return []

        bid = float(bbo["bid"]["px"]) if "bid" in bbo else None
        ask = float(bbo["ask"]["px"]) if "ask" in bbo else None
        if not bid or not ask:
            return []

        mid = (bid + ask) / 2
        pip = self.pip_size
        signals = []

        nearest = self.sr.get_nearest_levels(mid, n=3)
        obs = self.sr.get_nearest_order_blocks(mid, n=2)

        for support in nearest["supports"]:
            if not self._is_near_level(mid, support.price, pip * 20):
                continue
            if support.score < 0.3:
                continue

            entry = support.price + pip
            tp = entry + pip * self.tp_pips
            sl = entry - pip * self.sl_pips

            ob_zone = self._find_confirming_ob(support.price, obs.get("bullish", []), "bullish")

            signal = TradeSignal(
                coin=self.coin, side="long", entry_price=round(entry, 2),
                tp_price=round(tp, 2), sl_price=round(sl, 2),
                sr_level=support.price, sr_kind="support",
                sr_strength=support.strength, ob_zone=ob_zone,
            )
            signals.append(signal)

        for resistance in nearest["resistances"]:
            if not self._is_near_level(mid, resistance.price, pip * 20):
                continue
            if resistance.score < 0.3:
                continue

            entry = resistance.price - pip
            tp = entry - pip * self.tp_pips
            sl = entry + pip * self.sl_pips

            ob_zone = self._find_confirming_ob(resistance.price, obs.get("bearish", []), "bearish")

            signal = TradeSignal(
                coin=self.coin, side="short", entry_price=round(entry, 2),
                tp_price=round(tp, 2), sl_price=round(sl, 2),
                sr_level=resistance.price, sr_kind="resistance",
                sr_strength=resistance.strength, ob_zone=ob_zone,
            )
            signals.append(signal)

        signals.sort(key=lambda s: s.sr_strength, reverse=True)
        return signals

    def execute_signal(self, signal: TradeSignal) -> dict | None:
        if not self.risk.can_trade(signal):
            log.info("Risk manager blocked trade: %s %s @ %.2f",
                     signal.side, signal.coin, signal.entry_price)
            return None

        is_buy = signal.side == "long"
        size = self.risk.compute_position_size(signal)
        if size <= 0:
            return None

        log.info("Placing %s %s %.4f @ %.2f (TP=%.2f SL=%.2f)",
                 signal.side, signal.coin, size, signal.entry_price,
                 signal.tp_price, signal.sl_price)

        result = self.client.place_order_with_tpsl(
            coin=signal.coin, is_buy=is_buy, size=size,
            entry_price=signal.entry_price,
            tp_price=signal.tp_price, sl_price=signal.sl_price,
        )

        self.active_signals.append(signal)
        self.risk.record_order(signal, size)
        return result

    def tick(self) -> list[dict]:
        results = []
        signals = self.scan_for_signals()

        for signal in signals[:1]:
            result = self.execute_signal(signal)
            if result:
                results.append({"signal": signal.to_dict(), "result": result})

        return results

    def _is_near_level(self, price: float, level: float, threshold: float) -> bool:
        return abs(price - level) <= threshold

    def _find_confirming_ob(self, sr_price: float, obs: list[OrderBlock],
                            kind: str) -> tuple | None:
        for ob in obs:
            if ob.kind == kind and ob.price_low <= sr_price <= ob.price_high:
                return (ob.price_low, ob.price_high)
        return None
