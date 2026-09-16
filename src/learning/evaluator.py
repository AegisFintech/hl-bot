import json
import time
import logging
import statistics
from pathlib import Path
from dataclasses import dataclass, asdict
from collections import defaultdict

log = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    trade_id: str
    coin: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float
    sr_level: float
    sr_kind: str
    sr_strength: float
    ob_zone: tuple | None
    entry_time: float
    exit_time: float
    exit_reason: str  # "tp", "sl", "manual"
    duration_s: float = 0.0

    def __post_init__(self):
        self.duration_s = self.exit_time - self.entry_time

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


class Evaluator:

    def __init__(self, trades_file: Path, performance_file: Path):
        self.trades_file = trades_file
        self.performance_file = performance_file
        self.trades: list[TradeRecord] = []
        self._load_trades()

    def _load_trades(self):
        if self.trades_file.exists():
            with open(self.trades_file) as f:
                data = json.load(f)
            self.trades = [TradeRecord(**t) for t in data]

    def _save_trades(self):
        with open(self.trades_file, "w") as f:
            json.dump([t.to_dict() for t in self.trades], f, indent=2)

    def record_trade(self, signal_dict: dict, exit_price: float, size: float,
                     pnl: float, exit_reason: str):
        entry_price = signal_dict["entry_price"]
        pnl_pct = pnl / (entry_price * size) if entry_price * size > 0 else 0

        record = TradeRecord(
            trade_id=f"{signal_dict['coin']}_{int(time.time()*1000)}",
            coin=signal_dict["coin"],
            side=signal_dict["side"],
            entry_price=entry_price,
            exit_price=exit_price,
            size=size,
            pnl=round(pnl, 6),
            pnl_pct=round(pnl_pct, 6),
            sr_level=signal_dict["sr_level"],
            sr_kind=signal_dict["sr_kind"],
            sr_strength=signal_dict["sr_strength"],
            ob_zone=signal_dict.get("ob_zone"),
            entry_time=signal_dict["timestamp"],
            exit_time=time.time(),
            exit_reason=exit_reason,
        )
        self.trades.append(record)
        self._save_trades()
        log.info("Recorded trade %s: %s %.6f PnL (%.4f%%)",
                 record.trade_id, exit_reason, pnl, pnl_pct * 100)
        return record

    def get_performance(self) -> dict:
        if not self.trades:
            return {"total_trades": 0}

        wins = [t for t in self.trades if t.pnl > 0]
        losses = [t for t in self.trades if t.pnl <= 0]
        pnls = [t.pnl for t in self.trades]

        total_pnl = sum(pnls)
        win_rate = len(wins) / len(self.trades) if self.trades else 0
        avg_win = statistics.mean([t.pnl for t in wins]) if wins else 0
        avg_loss = statistics.mean([t.pnl for t in losses]) if losses else 0
        profit_factor = abs(sum(t.pnl for t in wins) / sum(t.pnl for t in losses)) if losses and sum(t.pnl for t in losses) != 0 else float("inf")

        sharpe = 0.0
        if len(pnls) > 1:
            mean_pnl = statistics.mean(pnls)
            std_pnl = statistics.stdev(pnls)
            if std_pnl > 0:
                sharpe = (mean_pnl / std_pnl) * (252 ** 0.5)

        perf = {
            "total_trades": len(self.trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 4),
            "total_pnl": round(total_pnl, 6),
            "avg_win": round(avg_win, 6),
            "avg_loss": round(avg_loss, 6),
            "profit_factor": round(profit_factor, 4),
            "sharpe_ratio": round(sharpe, 4),
            "avg_duration_s": round(statistics.mean([t.duration_s for t in self.trades]), 1),
        }

        self._save_performance(perf)
        return perf

    def analyze_sr_patterns(self) -> dict:
        if len(self.trades) < 5:
            return {}

        by_kind = defaultdict(list)
        by_strength_bucket = defaultdict(list)
        with_ob = []
        without_ob = []

        for t in self.trades:
            by_kind[t.sr_kind].append(t)

            bucket = round(t.sr_strength, 1)
            by_strength_bucket[bucket].append(t)

            if t.ob_zone:
                with_ob.append(t)
            else:
                without_ob.append(t)

        analysis = {}

        for kind, trades in by_kind.items():
            wins = sum(1 for t in trades if t.pnl > 0)
            analysis[f"{kind}_win_rate"] = round(wins / len(trades), 4) if trades else 0
            analysis[f"{kind}_avg_pnl"] = round(statistics.mean([t.pnl for t in trades]), 6)

        for bucket, trades in sorted(by_strength_bucket.items()):
            wins = sum(1 for t in trades if t.pnl > 0)
            analysis[f"strength_{bucket}_win_rate"] = round(wins / len(trades), 4) if trades else 0

        if with_ob:
            ob_wins = sum(1 for t in with_ob if t.pnl > 0)
            analysis["ob_confirmed_win_rate"] = round(ob_wins / len(with_ob), 4)
        if without_ob:
            no_ob_wins = sum(1 for t in without_ob if t.pnl > 0)
            analysis["no_ob_win_rate"] = round(no_ob_wins / len(without_ob), 4)

        return analysis

    def suggest_adjustments(self) -> dict:
        if len(self.trades) < 10:
            return {}

        perf = self.get_performance()
        pattern = self.analyze_sr_patterns()
        adjustments = {}

        if perf["win_rate"] < 0.5:
            adjustments["min_touches"] = 3
            log.info("Low win rate (%.1f%%) — increasing min_touches to 3", perf["win_rate"] * 100)

        if pattern.get("ob_confirmed_win_rate", 0) > pattern.get("no_ob_win_rate", 0) + 0.1:
            adjustments["require_ob_confirmation"] = True
            log.info("OB-confirmed trades outperform — suggesting OB requirement")

        support_wr = pattern.get("support_win_rate", 0.5)
        resistance_wr = pattern.get("resistance_win_rate", 0.5)
        if abs(support_wr - resistance_wr) > 0.15:
            better = "support" if support_wr > resistance_wr else "resistance"
            adjustments["preferred_side"] = better
            log.info("%s trades performing better (%.1f%% vs %.1f%%)",
                     better, max(support_wr, resistance_wr) * 100,
                     min(support_wr, resistance_wr) * 100)

        best_bucket = max(
            [(b, d) for b, d in pattern.items() if b.startswith("strength_") and b.endswith("_win_rate")],
            key=lambda x: x[1], default=None
        )
        if best_bucket and best_bucket[1] > perf["win_rate"] + 0.05:
            min_strength = float(best_bucket[0].split("_")[1])
            adjustments["min_sr_strength"] = min_strength
            log.info("Strength bucket %.1f has best win rate — suggesting minimum", min_strength)

        return adjustments

    def _save_performance(self, perf: dict):
        with open(self.performance_file, "w") as f:
            json.dump(perf, f, indent=2)

    def get_recent_trades(self, n: int = 20) -> list[dict]:
        return [t.to_dict() for t in self.trades[-n:]]

    def get_cumulative_pnl(self) -> list[dict]:
        cumulative = 0.0
        points = []
        for t in self.trades:
            cumulative += t.pnl
            points.append({"time": t.exit_time, "pnl": round(cumulative, 6)})
        return points
