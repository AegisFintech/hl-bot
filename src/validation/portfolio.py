"""Offline aligned daily-return/capacity diagnostics; never changes allocations."""

from datetime import date
from math import sqrt
from statistics import mean
from .evidence import number


def review_portfolio(payload):
    strategies = payload["strategies"]
    weights = payload["weights"]
    if len(strategies) < 2 or set(strategies) != set(weights):
        raise ValueError("At least two strategies with matching weights required")
    weights = {k: number(v) for k, v in weights.items()}
    if any(v < 0 for v in weights.values()) or sum(weights.values()) > 1 + 1e-12:
        raise ValueError("Only unlevered nonnegative diagnostic weights supported")
    data = {}
    for name, strategy in strategies.items():
        data[name] = {}
        for day, value in strategy["daily_returns"].items():
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError("Daily dates must be canonical ISO UTC dates")
            value = number(value)
            if value <= -1:
                raise ValueError("Return outside simple NAV model domain")
            data[name][day] = value
    common = sorted(set.intersection(*(set(v) for v in data.values())))
    correlations = []
    names = sorted(strategies)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            x = [data[a][d] for d in common]
            y = [data[b][d] for d in common]
            xm, ym = (mean(x), mean(y)) if x else (0, 0)
            denom = sqrt(sum((v - xm) ** 2 for v in x) * sum((v - ym) ** 2 for v in y))
            corr = (
                sum((v - xm) * (w - ym) for v, w in zip(x, y)) / denom
                if denom
                else None
            )
            correlations.append(dict(a=a, b=b, correlation=corr))
    nav = peak = 1.0
    drawdown = 0.0
    for day in common:
        nav *= 1 + sum(weights[k] * data[k][day] for k in names)
        peak = max(peak, nav)
        drawdown = max(drawdown, 1 - nav / peak)
    stresses = []
    for scenario in payload.get("stress_scenarios", []):
        shock = scenario["returns"]
        if set(shock) != set(names):
            raise ValueError("Joint stress must cover every strategy")
        stresses.append(
            dict(
                name=scenario["name"],
                weighted_return=sum(weights[k] * number(shock[k]) for k in names),
            )
        )
    blockers = []
    if len(common) < 30:
        blockers.append("Fewer than 30 fully aligned supplied days")
    if any(
        s.get("evidence_status") != "independently_reviewed"
        for s in strategies.values()
    ):
        blockers.append("Multiple independently reviewed strategies unavailable")
    if drawdown >= 0.05:
        blockers.append("Supplied weighted history reaches the 5% drawdown limit")
    if not stresses or any(s["weighted_return"] <= -0.05 for s in stresses):
        blockers.append("Joint stress missing or reaches the account limit")
    capacity = payload.get("capacity")
    if capacity:
        depth = number(capacity["executable_depth_usd"])
        order = number(capacity["order_notional_usd"])
        limit = number(capacity["max_depth_participation"])
        if depth <= 0 or order <= 0 or not 0 < limit <= 1:
            raise ValueError("Invalid supplied capacity assumptions")
        ratio = order / depth
        if ratio > limit:
            blockers.append(
                "Proposed order exceeds declared executable-depth participation"
            )
    else:
        ratio = None
        blockers.append("Executable-depth capacity assumptions missing")
    return dict(
        status="manual_review_only" if not blockers else "blocked",
        approved=False,
        aligned_days=len(common),
        aligned_start=common[0] if common else None,
        aligned_end=common[-1] if common else None,
        excluded_dates={k: len(v) - len(common) for k, v in data.items()},
        weights=weights,
        supplied_history_nav_multiple=nav,
        supplied_history_max_drawdown=drawdown,
        correlations=correlations,
        stress_scenarios=stresses,
        depth_participation=ratio,
        blockers=blockers,
        scope="Supplied net daily return fractions; no missing-date forward filling. Constant daily rebalanced weights assume free rebalancing and leave unused weight in cash. Correlation is unstable and not a hedge guarantee. Depth and shocks are supplied scenarios, not measured capacity or forecasts. Historical drawdown is not a bound on future loss. No sizing, promotion or real-fund authorization.",
    )
