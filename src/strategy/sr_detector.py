import numpy as np
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class SRLevel:
    price: float
    kind: str  # "support" or "resistance"
    strength: float  # 0-1 confidence
    touches: int = 0
    volume_weight: float = 0.0
    last_touch_idx: int = 0

    @property
    def score(self) -> float:
        return self.strength * (1 + 0.2 * min(self.touches, 5)) * (1 + self.volume_weight)


@dataclass
class OrderBlock:
    price_high: float
    price_low: float
    kind: str  # "bullish" or "bearish"
    volume: float = 0.0
    idx: int = 0

    @property
    def mid(self) -> float:
        return (self.price_high + self.price_low) / 2


class SRDetector:

    def __init__(self, lookback: int = 100, cluster_pct: float = 0.002,
                 swing_window: int = 5, min_touches: int = 3):
        self.lookback = lookback
        self.cluster_pct = cluster_pct
        self.swing_window = swing_window
        self.min_touches = min_touches
        self._levels: list[SRLevel] = []
        self._order_blocks: list[OrderBlock] = []
        self._param_adjustments: dict = {}

    def apply_adjustments(self, adjustments: dict):
        self._param_adjustments = adjustments
        if "lookback" in adjustments:
            self.lookback = adjustments["lookback"]
        if "cluster_pct" in adjustments:
            self.cluster_pct = adjustments["cluster_pct"]
        if "swing_window" in adjustments:
            self.swing_window = adjustments["swing_window"]
        if "min_touches" in adjustments:
            self.min_touches = adjustments["min_touches"]

    def detect(self, candles: list[dict]) -> list[SRLevel]:
        if len(candles) < self.swing_window * 2 + 1:
            return []

        candles = candles[-self.lookback:]
        highs = np.array([float(c["h"]) for c in candles])
        lows = np.array([float(c["l"]) for c in candles])
        closes = np.array([float(c["c"]) for c in candles])
        volumes = np.array([float(c["v"]) for c in candles])

        swing_highs = self._find_swing_highs(highs)
        swing_lows = self._find_swing_lows(lows)

        raw_levels = []
        for idx in swing_highs:
            raw_levels.append(("resistance", highs[idx], volumes[idx], idx))
        for idx in swing_lows:
            raw_levels.append(("support", lows[idx], volumes[idx], idx))

        clustered = self._cluster_levels(raw_levels, closes[-1])
        self._levels = [l for l in clustered if l.touches >= self.min_touches]
        self._levels.sort(key=lambda l: l.score, reverse=True)
        return self._levels

    def detect_order_blocks(self, candles: list[dict]) -> list[OrderBlock]:
        if len(candles) < 3:
            return []

        candles = candles[-self.lookback:]
        self._order_blocks = []

        for i in range(1, len(candles) - 1):
            prev = candles[i - 1]
            curr = candles[i]
            nxt = candles[i + 1]

            prev_close, prev_open = float(prev["c"]), float(prev["o"])
            curr_close, curr_open = float(curr["c"]), float(curr["o"])
            nxt_close, nxt_open = float(nxt["c"]), float(nxt["o"])
            curr_vol = float(curr["v"])

            body_prev = abs(prev_close - prev_open)
            body_nxt = abs(nxt_close - nxt_open)
            avg_body = (body_prev + body_nxt) / 2 if (body_prev + body_nxt) > 0 else 1

            # Bullish OB: down candle followed by strong up move
            if curr_close < curr_open and nxt_close > nxt_open:
                if body_nxt > avg_body * 1.5:
                    self._order_blocks.append(OrderBlock(
                        price_high=float(curr["h"]),
                        price_low=float(curr["l"]),
                        kind="bullish",
                        volume=curr_vol,
                        idx=i,
                    ))

            # Bearish OB: up candle followed by strong down move
            if curr_close > curr_open and nxt_close < nxt_open:
                if body_nxt > avg_body * 1.5:
                    self._order_blocks.append(OrderBlock(
                        price_high=float(curr["h"]),
                        price_low=float(curr["l"]),
                        kind="bearish",
                        volume=curr_vol,
                        idx=i,
                    ))

        return self._order_blocks

    def get_nearest_levels(self, price: float, n: int = 3) -> dict:
        supports = sorted(
            [l for l in self._levels if l.price < price],
            key=lambda l: price - l.price,
        )[:n]
        resistances = sorted(
            [l for l in self._levels if l.price > price],
            key=lambda l: l.price - price,
        )[:n]
        return {"supports": supports, "resistances": resistances}

    def get_nearest_order_blocks(self, price: float, n: int = 2) -> dict:
        bullish = sorted(
            [ob for ob in self._order_blocks if ob.mid < price],
            key=lambda ob: price - ob.mid,
        )[:n]
        bearish = sorted(
            [ob for ob in self._order_blocks if ob.mid > price],
            key=lambda ob: ob.mid - price,
        )[:n]
        return {"bullish": bullish, "bearish": bearish}

    def _find_swing_highs(self, highs: np.ndarray) -> list[int]:
        w = self.swing_window
        swings = []
        for i in range(w, len(highs) - w):
            if highs[i] == max(highs[i - w:i + w + 1]):
                swings.append(i)
        return swings

    def _find_swing_lows(self, lows: np.ndarray) -> list[int]:
        w = self.swing_window
        swings = []
        for i in range(w, len(lows) - w):
            if lows[i] == min(lows[i - w:i + w + 1]):
                swings.append(i)
        return swings

    def _cluster_levels(self, raw_levels: list[tuple], current_price: float) -> list[SRLevel]:
        if not raw_levels:
            return []

        raw_levels.sort(key=lambda x: x[1])
        clusters = []
        used = set()

        for i, (kind, price, vol, idx) in enumerate(raw_levels):
            if i in used:
                continue
            cluster_prices = [price]
            cluster_vols = [vol]
            cluster_kinds = [kind]
            cluster_indices = [idx]
            used.add(i)

            for j in range(i + 1, len(raw_levels)):
                if j in used:
                    continue
                if abs(raw_levels[j][1] - price) / price < self.cluster_pct:
                    cluster_prices.append(raw_levels[j][1])
                    cluster_vols.append(raw_levels[j][2])
                    cluster_kinds.append(raw_levels[j][0])
                    cluster_indices.append(raw_levels[j][3])
                    used.add(j)

            avg_price = np.mean(cluster_prices)
            total_vol = sum(cluster_vols)
            max_vol = max(cluster_vols) if cluster_vols else 0
            touches = len(cluster_prices)

            kind_counts = defaultdict(int)
            for k in cluster_kinds:
                kind_counts[k] += 1
            dominant_kind = max(kind_counts, key=kind_counts.get)

            distance_pct = abs(avg_price - current_price) / current_price
            proximity_bonus = max(0, 1 - distance_pct * 20)

            strength = min(1.0, (touches / 5) * 0.5 + proximity_bonus * 0.3 + 0.2)

            clusters.append(SRLevel(
                price=round(avg_price, 2),
                kind=dominant_kind,
                strength=round(strength, 3),
                touches=touches,
                volume_weight=round(total_vol / (max_vol * touches) if max_vol > 0 else 0, 3),
                last_touch_idx=max(cluster_indices),
            ))

        return clusters
