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
    signal_score: float = 0.0
    with_trend: bool = False
    has_ob: bool = False
    has_rejection: bool = False
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return asdict(self)


class Scalper:

    def __init__(self, client: HyperliquidClient, sr_detector: SRDetector,
                 risk_manager: RiskManager, coin: str, tp_pips: int = 30,
                 sl_pips: int = 15, pip_size: float | None = None,
                 proximity_pct: float = 0.003):
        self.client = client
        self.sr = sr_detector
        self.risk = risk_manager
        self.coin = coin
        self.tp_pips = tp_pips
        self.sl_pips = sl_pips
        self._pip_size = pip_size
        self.proximity_pct = proximity_pct
        self.active_signals: list[TradeSignal] = []
        self._last_sr_update = 0.0
        self._sr_update_interval = 60.0
        self._last_debug_log = 0.0
        self._last_signal_meta: dict = {}
        self._recent_entries: dict[float, float] = {}
        self._signal_cooldown = 300.0
        self._pip_cache = 0.0
        self._pip_cache_time = 0.0
        self._blacklisted_levels: dict[float, float] = {}
        self._blacklist_duration = 3600.0
        self._last_scan_time = 0.0
        self._scan_interval = 5.0
        self._last_mid = 0.0

    @property
    def pip_size(self) -> float:
        if self._pip_size is not None:
            return self._pip_size
        now = time.time()
        if self._pip_cache and now - self._pip_cache_time < 60.0:
            return self._pip_cache
        price = self.client.get_mid_price(self.coin)
        if price > 10000:
            pip = 1.0
        elif price > 1000:
            pip = 0.1
        elif price > 100:
            pip = 0.01
        else:
            pip = 0.001
        self._pip_cache = pip
        self._pip_cache_time = now
        return pip

    def update_sr_levels(self, candles: list[dict] | None = None):
        if candles is None:
            candles = self.client.get_cached_candles(self.coin)
            if len(candles) < self.sr.lookback:
                lookback_ms = max(self.sr.lookback, 1000) * 60 * 1000
                candles = self.client.get_candles(self.coin, "1m", lookback_ms)

        self.sr.detect(candles)
        self.sr.detect_order_blocks(candles)
        self._last_sr_update = time.time()
        log.info("Updated S/R levels: %d levels, %d order blocks",
                 len(self.sr._levels), len(self.sr._order_blocks))

    def _is_level_blacklisted(self, level_price: float) -> bool:
        now = time.time()
        cluster_range = level_price * self.sr.cluster_pct
        for bl_price, bl_time in list(self._blacklisted_levels.items()):
            if now - bl_time > self._blacklist_duration:
                del self._blacklisted_levels[bl_price]
                continue
            if abs(level_price - bl_price) <= cluster_range:
                return True
        return False

    def blacklist_level(self, level_price: float):
        self._blacklisted_levels[level_price] = time.time()
        log.info("Blacklisted S/R level %.2f for %ds after SL hit", level_price, int(self._blacklist_duration))

    def _has_rejection_candle(self, candles: list, level_price: float, side: str) -> bool:
        if len(candles) < 3:
            return False
        for candle in candles[-3:]:
            o, h, l, c = float(candle["o"]), float(candle["h"]), float(candle["l"]), float(candle["c"])
            body = abs(c - o)
            full_range = h - l
            if full_range <= 0:
                continue
            if side == "long":
                lower_wick = min(o, c) - l
                if lower_wick > body and l <= level_price * 1.001:
                    return True
            else:
                upper_wick = h - max(o, c)
                if upper_wick > body and h >= level_price * 0.999:
                    return True
        return False

    def _is_pullback(self, candles: list, level_price: float, side: str) -> bool:
        if len(candles) < 20:
            return False
        recent = candles[-20:]
        closes = [float(c["c"]) for c in recent]
        if side == "long":
            peak = max(closes[:-5]) if len(closes) > 5 else max(closes)
            retrace = peak - level_price
            return retrace > level_price * 0.001
        else:
            trough = min(closes[:-5]) if len(closes) > 5 else min(closes)
            retrace = level_price - trough
            return retrace > level_price * 0.001

    def _score_signal(self, level: SRLevel, trend: str, side: str,
                      candles: list, obs: list[OrderBlock], ob_kind: str) -> float:
        score = level.score
        with_trend = (side == "long" and trend == "up") or (side == "short" and trend == "down")
        counter_trend = (side == "long" and trend == "down") or (side == "short" and trend == "up")
        if counter_trend:
            return -1.0
        if not self._is_pullback(candles, level.price, side):
            return -1.0
        if with_trend:
            score *= 1.8
        elif trend == "neutral":
            score *= 1.0
        has_rejection = self._has_rejection_candle(candles, level.price, side)
        has_ob = self._find_confirming_ob(level.price, obs, ob_kind)
        if has_rejection:
            score *= 1.3
        if has_ob:
            score *= 1.3
        self._last_signal_meta = {
            "with_trend": with_trend,
            "has_rejection": has_rejection,
            "has_ob": has_ob is not None,
        }
        return score

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

        if now - self._last_scan_time < self._scan_interval:
            pip = self.pip_size
            if self._last_mid and abs(mid - self._last_mid) < pip * 2:
                return []
        self._last_scan_time = now
        self._last_mid = mid

        pip = self.pip_size
        threshold = mid * self.proximity_pct
        signals = []

        candles = self.client.get_cached_candles(self.coin)
        if len(candles) < 50:
            if not hasattr(self, '_rest_candles') or now - getattr(self, '_rest_candles_time', 0) > 60:
                self._rest_candles = self.client.get_candles(self.coin, "1m", 100 * 60 * 1000)
                self._rest_candles_time = now
            candles = self._rest_candles
        trend = self._get_trend(candles)

        nearest = self.sr.get_nearest_levels(mid, n=3)
        obs = self.sr.get_nearest_order_blocks(mid, n=2)

        if now - self._last_debug_log > 60:
            supports = nearest["supports"]
            resistances = nearest["resistances"]
            nearest_dist = None
            if supports:
                nearest_dist = abs(mid - supports[0].price)
            if resistances:
                r_dist = abs(mid - resistances[0].price)
                nearest_dist = min(nearest_dist, r_dist) if nearest_dist else r_dist
            log.info("Scan: mid=%.2f threshold=%.2f nearest_sr=%.2f supports=%d resistances=%d trend=%s bl=%d",
                     mid, threshold, nearest_dist or 0, len(supports), len(resistances), trend,
                     len(self._blacklisted_levels))
            self._last_debug_log = now

        for support in nearest["supports"]:
            if not self._is_near_level(mid, support.price, threshold):
                continue
            if self._is_level_blacklisted(support.price):
                continue

            score = self._score_signal(support, trend, "long", candles,
                                       obs.get("bullish", []), "bullish")
            if score < 0.8:
                continue

            entry = self.client.round_price(self.coin, support.price + pip)
            tp = self.client.round_price(self.coin, entry + pip * self.tp_pips)
            sl = self.client.round_price(self.coin, entry - pip * self.sl_pips)

            ob_zone = self._find_confirming_ob(support.price, obs.get("bullish", []), "bullish")

            meta = self._last_signal_meta
            signal = TradeSignal(
                coin=self.coin, side="long", entry_price=entry,
                tp_price=tp, sl_price=sl,
                sr_level=support.price, sr_kind="support",
                sr_strength=support.strength, ob_zone=ob_zone,
                signal_score=score,
                with_trend=meta.get("with_trend", False),
                has_ob=meta.get("has_ob", False),
                has_rejection=meta.get("has_rejection", False),
            )
            signals.append(signal)

        for resistance in nearest["resistances"]:
            if not self._is_near_level(mid, resistance.price, threshold):
                continue
            if self._is_level_blacklisted(resistance.price):
                continue

            score = self._score_signal(resistance, trend, "short", candles,
                                       obs.get("bearish", []), "bearish")
            if score < 0.8:
                continue

            entry = self.client.round_price(self.coin, resistance.price - pip)
            tp = self.client.round_price(self.coin, entry - pip * self.tp_pips)
            sl = self.client.round_price(self.coin, entry + pip * self.sl_pips)

            ob_zone = self._find_confirming_ob(resistance.price, obs.get("bearish", []), "bearish")

            meta = self._last_signal_meta
            signal = TradeSignal(
                coin=self.coin, side="short", entry_price=entry,
                tp_price=tp, sl_price=sl,
                sr_level=resistance.price, sr_kind="resistance",
                sr_strength=resistance.strength, ob_zone=ob_zone,
                signal_score=score,
                with_trend=meta.get("with_trend", False),
                has_ob=meta.get("has_ob", False),
                has_rejection=meta.get("has_rejection", False),
            )
            signals.append(signal)

        signals.sort(key=lambda s: s.signal_score, reverse=True)
        return signals

    def build_order_payload(self, signal: TradeSignal) -> dict | None:
        if not self.risk.can_trade(signal):
            return None
        is_buy = signal.side == "long"
        size = self.risk.compute_position_size(signal)
        if size <= 0:
            return None
        size = self.client.round_size(signal.coin, size)
        exit_side = not is_buy
        return {
            "coin": signal.coin,
            "is_buy": is_buy,
            "size": size,
            "entry_price": signal.entry_price,
            "tp_price": signal.tp_price,
            "sl_price": signal.sl_price,
            "side": signal.side,
            "sr_level": signal.sr_level,
            "sr_kind": signal.sr_kind,
            "orders": [
                {"coin": signal.coin, "is_buy": is_buy, "sz": size, "limit_px": signal.entry_price,
                 "order_type": {"limit": {"tif": "Gtc"}}, "reduce_only": False},
                {"coin": signal.coin, "is_buy": exit_side, "sz": size, "limit_px": signal.tp_price,
                 "order_type": {"trigger": {"triggerPx": signal.tp_price, "isMarket": False, "tpsl": "tp"}},
                 "reduce_only": True},
                {"coin": signal.coin, "is_buy": exit_side, "sz": size, "limit_px": signal.sl_price,
                 "order_type": {"trigger": {"triggerPx": signal.sl_price, "isMarket": True, "tpsl": "sl"}},
                 "reduce_only": True},
            ],
            "grouping": "normalTpsl",
        }

    def _is_level_on_cooldown(self, level_price: float) -> bool:
        now = time.time()
        cluster_range = level_price * self.sr.cluster_pct
        for entry_price, entry_time in self._recent_entries.items():
            if now - entry_time < self._signal_cooldown and abs(level_price - entry_price) <= cluster_range:
                return True
        return False

    def execute_signal(self, signal: TradeSignal) -> dict | None:
        if self._is_level_on_cooldown(signal.sr_level):
            return None

        if not self.risk.can_trade(signal):
            return None

        is_buy = signal.side == "long"
        size = self.risk.compute_position_size(signal)
        if size <= 0:
            return None

        log.info("Placing %s %s %.4f @ %.2f (TP=%.2f SL=%.2f score=%.2f str=%.2f)",
                 signal.side, signal.coin, size, signal.entry_price,
                 signal.tp_price, signal.sl_price, signal.signal_score, signal.sr_strength)

        result = self.client.place_order_with_tpsl(
            coin=signal.coin, is_buy=is_buy, size=size,
            entry_price=signal.entry_price,
            tp_price=signal.tp_price, sl_price=signal.sl_price,
        )

        log.info("Order result: %s", result)
        statuses = result.get("response", {}).get("data", {}).get("statuses", [])
        has_error = any(isinstance(s, dict) and "error" in s for s in statuses)
        if has_error:
            log.warning("Order rejected: %s", statuses)
            return None

        self._recent_entries[signal.sr_level] = time.time()
        self.active_signals.append(signal)
        if len(self.active_signals) > 200:
            self.active_signals = self.active_signals[-200:]
        self.risk.record_order(signal, size)
        return result

    def tick(self) -> list[dict]:
        cutoff = time.time() - self._signal_cooldown
        self._recent_entries = {k: v for k, v in self._recent_entries.items() if v > cutoff}

        results = []
        signals = self.scan_for_signals()

        for signal in signals[:1]:
            result = self.execute_signal(signal)
            if result:
                results.append({"signal": signal.to_dict(), "result": result})

        return results

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        if not values:
            return 0.0
        k = 2.0 / (period + 1)
        ema = values[0]
        for v in values[1:]:
            ema = v * k + ema * (1 - k)
        return ema

    def _get_trend(self, candles: list) -> str:
        if len(candles) < 30:
            return "neutral"
        closes = [float(c["c"]) for c in candles[-50:]]
        ema9 = self._ema(closes, 9)
        ema21 = self._ema(closes, 21)
        if ema21 == 0:
            return "neutral"
        spread_pct = (ema9 - ema21) / ema21
        if spread_pct > 0.0002:
            return "up"
        if spread_pct < -0.0002:
            return "down"
        return "neutral"

    def _is_near_level(self, price: float, level: float, threshold: float) -> bool:
        return abs(price - level) <= threshold

    def _find_confirming_ob(self, sr_price: float, obs: list[OrderBlock],
                            kind: str) -> tuple | None:
        for ob in obs:
            if ob.kind == kind and ob.price_low <= sr_price <= ob.price_high:
                return (ob.price_low, ob.price_high)
        return None
