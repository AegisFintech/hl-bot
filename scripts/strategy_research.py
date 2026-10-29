"""Pre-declared, chronological strategy selection on cached public history.

Selection uses only the in-sample window; every candidate's out-of-sample result
is reported so the selection can be checked rather than trusted. Sharpe ratios
are deflated for the number of candidates tried (Bailey & Lopez de Prado, 2014).
Results are simulations with modeled costs, not fills or forecasts.

Usage:
  python3 scripts/fetch_history.py --source binance --coins BTC,ETH,SOL --interval 1h --since 2021-01 --funding
  python3 scripts/strategy_research.py --source binance --coins BTC,ETH,SOL --intervals 1h,4h
"""

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.fetch_history import HISTORY, INTERVAL_MS  # noqa: E402
from src.strategy.library import Bars, build  # noqa: E402
from src.validation.backtest import Costs, Risk, backtest  # noqa: E402

# Fixed before looking at results: conventional parameters only, no fitting.
CANDIDATES = [
    ("donchian", dict(entry=20, exit=10)),
    ("donchian", dict(entry=55, exit=20)),
    ("donchian", dict(entry=20, exit=10, trend=200)),
    ("donchian", dict(entry=55, exit=20, trend=200)),
    ("donchian", dict(entry=20, exit=10, allow_short=False)),
    ("ema_trend", dict(fast=20, slow=100)),
    ("ema_trend", dict(fast=50, slow=200)),
    ("ema_trend", dict(fast=20, slow=100, allow_short=False)),
    ("tsmom", dict(lookback=72)),
    ("tsmom", dict(lookback=168)),
    ("tsmom", dict(lookback=336)),
    ("tsmom", dict(lookback=168, allow_short=False)),
    ("rsi_reversion", dict()),
    ("rsi_reversion", dict(low=5.0, high=95.0)),
]
RISK_LEVELS = [0.0025, 0.005, 0.0075, 0.01]
MIN_IS_TRADES = 30
MAX_IS_DRAWDOWN_PCT = 25.0


def load(source, coins, interval):
    folder = HISTORY / source
    markets, funding = {}, {}
    for coin in coins:
        path = folder / f"{coin}-{interval}.json"
        if not path.exists():
            print(f"missing {path.relative_to(ROOT)}; run scripts/fetch_history.py first", file=sys.stderr)
            continue
        markets[coin] = Bars.from_candles(json.loads(path.read_text()))
        rates = folder / f"{coin}-funding.json"
        if rates.exists():
            funding[coin] = {int(k): float(v) for k, v in json.loads(rates.read_text()).items()}
    return markets, funding


def deflated_sharpe(sharpe_daily, trials_sharpe_daily, n_obs, skew, kurt):
    """Probability that the true Sharpe exceeds the best of ``N`` unskilled trials."""
    n = len(trials_sharpe_daily)
    if n < 2 or n_obs < 3:
        return None
    var = statistics.pvariance(trials_sharpe_daily)
    gamma = 0.5772156649
    z = statistics.NormalDist()
    expected_max = math.sqrt(var) * ((1 - gamma) * z.inv_cdf(1 - 1 / n) + gamma * z.inv_cdf(1 - 1 / (n * math.e)))
    denom = math.sqrt(max(1e-12, 1 - skew * sharpe_daily + (kurt - 1) / 4 * sharpe_daily ** 2))
    return z.cdf((sharpe_daily - expected_max) * math.sqrt(n_obs - 1) / denom)


def daily_returns(curve, initial):
    daily = {}
    for stamp, value in curve:
        daily[stamp // 86_400_000] = value
    values = [initial] + [daily[d] for d in sorted(daily)]
    return [b / a - 1 for a, b in zip(values, values[1:]) if a > 0]


def moments(returns):
    if len(returns) < 3:
        return 0.0, 0.0, 3.0
    mean, sd = statistics.fmean(returns), statistics.pstdev(returns)
    if sd == 0:
        return 0.0, 0.0, 3.0
    skew = statistics.fmean(((r - mean) / sd) ** 3 for r in returns)
    kurt = statistics.fmean(((r - mean) / sd) ** 4 for r in returns)
    return mean / sd, skew, kurt


def spearman(xs, ys):
    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        for rank, i in enumerate(order):
            out[i] = rank
        return out
    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def compact(result):
    keep = ("return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "sortino", "trades", "trades_per_day",
            "win_rate_pct", "profit_factor", "avg_r", "fees_usd", "funding_usd", "drawdown_breaker_trips",
            "exposure_pct", "yearly_return_pct", "days")
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in result.items() if k in keep}


def day(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="binance", help="data/history/<source>")
    parser.add_argument("--coins", default="BTC,ETH,SOL")
    parser.add_argument("--intervals", default="1h,4h")
    parser.add_argument("--split", type=float, default=0.7, help="in-sample fraction of the timeline")
    parser.add_argument("--risk", type=float, default=0.005, help="risk per trade while ranking candidates")
    parser.add_argument("--breaker", type=float, default=0.05)
    parser.add_argument("--cooldown", type=float, default=12.0)
    parser.add_argument("--max-positions", type=int, default=3)
    parser.add_argument("--out", default=str(ROOT / "docs" / "strategy-research.json"))
    args = parser.parse_args(argv)
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    costs = Costs()
    rows = []
    windows = {}
    for interval in args.intervals.split(","):
        markets, funding = load(args.source, coins, interval)
        if not markets:
            continue
        times = sorted({t for bars in markets.values() for t in bars.t})
        split = times[int(len(times) * args.split)]
        windows[interval] = dict(start=day(times[0]), split=day(split), end=day(times[-1]), coins=sorted(markets))
        risk = Risk(risk_per_trade=args.risk, drawdown_limit=args.breaker, cooldown_hours=args.cooldown,
                    max_positions=args.max_positions)
        for name, params in CANDIDATES:
            strategy = build(name, **params)
            ins, _, ins_curve = backtest(strategy, markets, INTERVAL_MS[interval], costs, risk, funding, end_time=split)
            oos, _, oos_curve = backtest(strategy, markets, INTERVAL_MS[interval], costs, risk, funding, start_time=split)
            rows.append(dict(interval=interval, strategy=name, params=params, label=strategy.label,
                             in_sample=compact(ins), out_of_sample=compact(oos),
                             _is_returns=daily_returns(ins_curve, 1000.0)))
            print(f"{interval:3s} {strategy.label[:72]:72s} IS sharpe {ins['sharpe']:6.2f} ret {ins['return_pct']:8.1f}% "
                  f"dd {ins['max_drawdown_pct']:5.1f}% n={ins['trades']:4d} | OOS sharpe {oos['sharpe']:6.2f} "
                  f"ret {oos['return_pct']:8.1f}% dd {oos['max_drawdown_pct']:5.1f}% n={oos['trades']:4d}")
    if not rows:
        raise SystemExit("No cached history; run scripts/fetch_history.py first")

    eligible = [r for r in rows if r["in_sample"]["trades"] >= MIN_IS_TRADES
                and r["in_sample"]["max_drawdown_pct"] <= MAX_IS_DRAWDOWN_PCT]
    best = max(eligible or rows, key=lambda r: r["in_sample"]["sharpe"])
    trial_sharpes = [moments(r["_is_returns"])[0] for r in rows]
    sr, skew, kurt = moments(best["_is_returns"])
    dsr = deflated_sharpe(sr, trial_sharpes, len(best["_is_returns"]), skew, kurt)

    interval = best["interval"]
    markets, funding = load(args.source, coins, interval)
    split = sorted({t for bars in markets.values() for t in bars.t})
    split = split[int(len(split) * args.split)]
    strategy = build(best["strategy"], **best["params"])
    sizing = []
    for level in RISK_LEVELS:
        risk = Risk(risk_per_trade=level, drawdown_limit=args.breaker, cooldown_hours=args.cooldown,
                    max_positions=args.max_positions)
        ins, _, _ = backtest(strategy, markets, INTERVAL_MS[interval], costs, risk, funding, end_time=split)
        oos, oos_trades, _ = backtest(strategy, markets, INTERVAL_MS[interval], costs, risk, funding, start_time=split)
        sizing.append(dict(risk_per_trade=level, in_sample=compact(ins), out_of_sample=compact(oos)))
    # Highest in-sample risk whose breaker trips stay at or below one per 30 days.
    affordable = [s for s in sizing if s["in_sample"]["drawdown_breaker_trips"] * 30
                  <= max(1.0, s["in_sample"]["days"])]
    chosen_risk = max(affordable or sizing[:1], key=lambda s: s["risk_per_trade"])
    per_coin = {}
    risk = Risk(risk_per_trade=chosen_risk["risk_per_trade"], drawdown_limit=args.breaker,
                cooldown_hours=args.cooldown, max_positions=args.max_positions)
    for coin, bars in markets.items():
        sub = {coin: bars}
        oos, _, _ = backtest(strategy, sub, INTERVAL_MS[interval], costs, risk,
                             {coin: funding[coin]} if coin in funding else {}, start_time=split)
        per_coin[coin] = compact(oos)

    report = dict(
        generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        data_source=f"data/history/{args.source} (public archives; not testnet fills)",
        windows=windows, costs=costs.__dict__,
        ranking_risk=dict(risk_per_trade=args.risk, breaker=args.breaker, cooldown_hours=args.cooldown,
                          max_positions=args.max_positions),
        selection_rule=f"Highest in-sample daily Sharpe with >= {MIN_IS_TRADES} trades and in-sample max drawdown "
                       f"<= {MAX_IS_DRAWDOWN_PCT}%; then the highest risk level with <= 1 breaker trip per 30 in-sample days.",
        candidates=[{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
        in_vs_out_of_sample_rank_correlation=spearman([r["in_sample"]["sharpe"] for r in rows],
                                                      [r["out_of_sample"]["sharpe"] for r in rows]),
        selected=dict(interval=interval, strategy=best["strategy"], params=best["params"], label=best["label"],
                      deflated_sharpe_probability=dsr, risk_per_trade=chosen_risk["risk_per_trade"],
                      sizing=sizing, out_of_sample_by_coin=per_coin),
        caveats=["Simulated from public OHLC archives with modeled fees, slippage and funding; not executed fills.",
                 "Testnet books are thinner than the archive venue; live slippage and fills can differ.",
                 "Past trends do not guarantee future trends; drawdown breaker trips flatten positions.",
                 f"{len(rows)} candidates were evaluated; the deflated Sharpe accounts for that search."],
    )
    report["env"] = {
        "STRATEGY": best["strategy"],
        "STRATEGY_PARAMS": json.dumps(best["params"]),
        "STRATEGY_INTERVAL": interval,
        "TRADE_COINS": ",".join(sorted(markets)),
        "RISK_PER_TRADE_PCT": f"{chosen_risk['risk_per_trade'] * 100:g}",
        "MAX_POSITIONS": str(args.max_positions),
        "DRAWDOWN_LIMIT_PCT": f"{args.breaker * 100:g}",
        "BREAKER_COOLDOWN_HOURS": f"{args.cooldown:g}",
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["selected"], indent=2))
    print("IS/OOS Sharpe rank correlation:", report["in_vs_out_of_sample_rank_correlation"])
    print("\nSuggested .env settings (review the out-of-sample results first):")
    for key, value in report["env"].items():
        print(f"{key}='{value}'" if key == "STRATEGY_PARAMS" else f"{key}={value}")


if __name__ == "__main__":
    main()
