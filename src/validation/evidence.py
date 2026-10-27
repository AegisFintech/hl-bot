"""Predeclared chronological review with dependent-day uncertainty; no promotion."""

import hashlib
import json
import math
import random
from datetime import datetime, timezone
from statistics import mean


def protocol_hash(protocol):
    return hashlib.sha256(
        json.dumps(
            protocol, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite evidence value")
    return result


def evaluate(rows, protocol, as_of):
    as_of = number(as_of)
    digest = protocol_hash(protocol)
    lock = number(protocol["locked_at"])
    begin, end = number(protocol["holdout_start"]), number(protocol["holdout_end"])
    embargo = number(protocol["embargo_s"])
    training_end = number(protocol["training_end"])
    if (
        not lock <= training_end < begin < end
        or begin - training_end < embargo
        or embargo < 0
    ):
        raise ValueError("Invalid chronological protocol or embargo")
    if (
        number(protocol["trials_attempted"]) != int(protocol["trials_attempted"])
        or int(protocol["trials_attempted"]) < 1
    ):
        raise ValueError("Trial inventory required")
    if int(protocol["min_days"]) < 2 or int(protocol["min_episodes"]) < 2:
        raise ValueError("Review requires multiple days and episodes")
    selected = []
    excluded = 0
    seen = set()
    for row in rows:
        ident = str(row["id"])
        if ident in seen:
            raise ValueError("Duplicate episode identity")
        seen.add(ident)
        start, finish = number(row["opened_at"]), number(row["closed_at"])
        observed = number(row["observed_at"])
        net = number(row["net_bps"])
        if finish < start or observed < finish:
            raise ValueError("Impossible episode chronology")
        if row["protocol_hash"] != digest or row["version"] != protocol["version"]:
            raise ValueError("Mixed or unregistered research cohort")
        if finish - start > embargo:
            raise ValueError("Embargo shorter than episode holding horizon")
        if begin <= start and finish <= end and observed <= as_of:
            selected.append(dict(row, opened_at=start, closed_at=finish, net_bps=net))
        else:
            excluded += 1
    sources = {r["source"] for r in selected}
    if len(sources) > 1:
        raise ValueError(
            "Actual fills, quote outcomes and simulations must be separate cohorts"
        )
    # Earliest-start greedy selection is descriptive, not an optimal tradable portfolio.
    windows = []
    last = -float("inf")
    for row in sorted(
        selected, key=lambda r: (r["opened_at"], r["closed_at"], str(r["id"]))
    ):
        if row["opened_at"] > last:
            windows.append(row)
            last = row["closed_at"]
    days = {}
    weeks = {}
    for row in windows:
        dt = datetime.fromtimestamp(row["closed_at"], timezone.utc)
        days.setdefault(dt.date().isoformat(), []).append(row["net_bps"])
        iso = dt.isocalendar()
        weeks.setdefault(f"{iso.year}-W{iso.week:02d}", []).append(row["net_bps"])
    daymeans = [mean(v) for v in days.values()]
    lower = None
    if len(daymeans) >= 2:
        # Day blocks retain within-day clustering, not all cross-day dependence.
        rng = random.Random(271027)
        draws = sorted(
            mean(rng.choices(daymeans, k=len(daymeans))) for _ in range(2000)
        )
        alpha = 0.05 / int(protocol["trials_attempted"])
        lower = draws[max(0, int(len(draws) * alpha) - 1)]
    stress = number(protocol["extra_cost_stress_bps"])
    if stress < 0:
        raise ValueError("Stress cost must not improve returns")
    blockers = []
    if protocol.get("trial_inventory_complete") is not True:
        blockers.append("Complete configuration trial inventory not attested")
    if 2000 * 0.05 / int(protocol["trials_attempted"]) < 20:
        blockers.append(
            "Bootstrap resolution insufficient for declared trial multiplicity"
        )
    if as_of < end:
        blockers.append("Untouched holdout period is still in progress")
    if len(days) < int(protocol["min_days"]):
        blockers.append("Insufficient distinct observed days")
    if len(windows) < int(protocol["min_episodes"]):
        blockers.append("Insufficient non-overlapping episodes")
    if not windows or sources != {"demo_fill"}:
        blockers.append("No actual demo-fill-only evaluation cohort")
    if any(r.get("funding_included") is not True for r in windows):
        blockers.append("Funding coverage incomplete")
    if lower is None or lower - stress <= 0:
        blockers.append("Cost-stressed day-block lower bound is not positive")
    if protocol.get("execution_stress_reviewed") is not True:
        blockers.append("Execution/cancel-race stress review missing")
    return dict(
        version=protocol["version"],
        protocol_hash=digest,
        source=next(iter(sources), None),
        status="review_ready" if not blockers else "not_ready",
        automatic_promotion=False,
        blockers=blockers,
        holdout=[begin, end],
        as_of=as_of,
        included=len(selected),
        excluded=excluded,
        nonoverlap_episodes=len(windows),
        observed_days=len(days),
        episode_mean_net_bps=mean([r["net_bps"] for r in windows]) if windows else None,
        equal_day_mean_net_bps=mean(daymeans) if daymeans else None,
        multiplicity_adjusted_day_bootstrap_lower_bps=lower,
        extra_cost_stress_bps=stress,
        weeks=[
            dict(week=k, n=len(v), mean_net_bps=mean(v))
            for k, v in sorted(weeks.items())
        ],
        scope="Offline review aid; thresholds are preregistered choices, not universal sufficiency. Earliest non-overlap windows remain dependent. Equal-day mean is not portfolio return. Day bootstrap misses cross-day dependence; trial count relies on an honest inventory. A small adjusted tail may have low bootstrap resolution. Review-ready is not approval or proof of an edge.",
    )
