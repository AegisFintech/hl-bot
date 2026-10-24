"""Fixed, observation-only experiments. No execution or parameter fitting."""

from collections import deque

EXPERIMENTS = (
    dict(
        id="failed_aggression",
        title="Failed whale aggression",
        priority=1,
        status="observing",
        mechanism="Large execution stalls at replenishing liquidity, then reverses.",
        rule="Fresh >=$100k print with opposing absorption; within 120s price reverses >=2bps from the armed quote.",
        invalidation="120s expiry, incomplete flow, stale quote or observation gap >15s.",
    ),
    dict(
        id="wall_defense",
        title="Wall defense and consumption",
        priority=1,
        status="observing defense; consumption blocked",
        mechanism="Persistent liquidity absorbs executions; defense can precede reversal.",
        rule="Wall persists >=30s, receives >=$25k executions in a sample and sampled refill >=50% of executions; confirm >=2bps away within 120s.",
        invalidation="Wall vanishes before confirmation. Consumption/retest needs cumulative executed-depth attribution.",
    ),
    dict(
        id="crowded_failure",
        title="Crowded-trade failure",
        priority=1,
        status="observing",
        mechanism="Crowded leverage loses price support and may unwind.",
        rule="Fresh hourly funding magnitude >=1bp, OI up >=0.5% over >=5m, then a >=5bps excursion fails back through its pre-break level.",
        invalidation="Context age >180s, funding reverses, price extends >=25bps, or 180s expiry.",
    ),
    dict(
        id="liquidation_aftershock",
        title="Liquidation aftershock",
        priority=2,
        status="blocked: verified broad liquidation feed",
        mechanism="Forced flow exhausts and liquidity recovers.",
        rule="Compare continuation with recovery after verified forced-flow deceleration.",
        invalidation="Watched-wallet events cannot represent a market-wide liquidation cascade.",
    ),
    dict(
        id="persistent_execution",
        title="Persistent whale execution",
        priority=2,
        status="blocked: execution-sequence attribution",
        mechanism="A participant splits a larger order and leaves sustained pressure.",
        rule="Require repeated directional executions, persistent public position change and remaining movement after delay.",
        invalidation="Unknown wallets/hedges and address churn prevent identity assumptions.",
    ),
    dict(
        id="relative_value",
        title="BTC/ETH relative value",
        priority=2,
        status="blocked: synchronized ETH quotes",
        mechanism="A temporary residual between related assets may revert.",
        rule="Freeze hedge ratio from past data; evaluate both legs, funding and correlation breaks.",
        invalidation="Unstable hedge ratio, mismatched timestamps or costs exceeding residual.",
    ),
    dict(
        id="funding_carry",
        title="Hedged funding carry",
        priority=2,
        status="blocked: hedge simulation and collateral model",
        mechanism="Leveraged demand pays a hedged holder over time.",
        rule="Model both legs, variable funding, basis, margin, borrow and four-leg execution costs.",
        invalidation="No funded secondary account; indicative basis is not executable carry.",
    ),
    dict(
        id="post_shock",
        title="Post-shock second move",
        priority=2,
        status="blocked: timestamped event source",
        mechanism="Price accepts or rejects a shock after its initial spike.",
        rule="Ignore initial spike; compare retest continuation with return into the prior range.",
        invalidation="Event-time leakage or entering before the confirmation.",
    ),
    dict(
        id="venue_leadership",
        title="Cross-venue price leadership",
        priority=3,
        status="blocked: synchronized streaming venue quotes",
        mechanism="A slower venue may adjust after price discovery elsewhere.",
        rule="Measure residual after observed feed/network delay and executable costs.",
        invalidation="Polling delay or transfer friction can manufacture apparent leads.",
    ),
)


class ExperimentEngine:
    """Bounded state machines: arm, confirm later, expire. Reset on data gaps."""

    def __init__(self):
        self.pending = {}
        self.context_history = deque(maxlen=240)
        self.last_time = None
        self.previous_mid = None
        self.seen_prints = deque(maxlen=2000)

    def evaluate(self, market, context=None):
        now = market["sampled_at"]
        if (
            not market["flow"]["complete"]
            or now - market["source_time"] > 15
            or market["source_time"] > now + 2
        ):
            self.pending.clear()
            self.last_time = None
            self.previous_mid = None
            return []
        if self.last_time is not None and (
            now <= self.last_time or now - self.last_time > 15
        ):
            self.pending.clear()
            self.previous_mid = None
        previous_mid = self.previous_mid
        self.last_time = now
        self.previous_mid = market["mid"]
        context_valid = (
            context
            and not context.get("error")
            and context.get("updated_at", 0) <= now + 2
            and now - context.get("updated_at", 0) <= 180
        )
        ctx = context.get("value", {}) if context_valid else {}
        funding = ctx.get("funding_hourly", 0)
        for direction in (1, -1):
            if abs(funding) < 0.0001 or (funding > 0) != (direction == -1):
                self.pending.pop(("crowded_failure", direction), None)
        events = []
        for key, state in list(self.pending.items()):
            kind, direction = key
            if now - state["armed_at"] > state["ttl"]:
                del self.pending[key]
                continue
            if kind == "wall_defense" and not any(
                w["side"] == state["wall_side"] and w["price"] == state["wall_price"]
                for w in market["walls"]
            ):
                del self.pending[key]
                continue
            if kind == "crowded_failure":
                if (
                    not ctx
                    or direction * (market["mid"] / state["anchor"] - 1) * 10000 < -25
                ):
                    del self.pending[key]
                    continue
                confirmed = (
                    direction * (market["mid"] / state["anchor"] - 1) * 10000 >= 0
                )
            else:
                confirmed = (
                    direction * (market["mid"] / state["anchor"] - 1) * 10000 >= 2
                )
            if now > state["armed_at"] and confirmed:
                events.append(
                    dict(kind=kind, direction=direction, reason=state["reason"])
                )
                del self.pending[key]

        absorption = market.get("absorption")
        if absorption:
            direction = 1 if absorption == "bullish" else -1
            side = "A" if direction == 1 else "B"
            fresh = [
                t
                for t in market["large_trades"]
                if t["side"] == side
                and 0 <= now - t["time"] <= 10
                and t["id"] not in self.seen_prints
            ]
            for trade in fresh:
                self.seen_prints.append(trade["id"])
            if fresh:
                self._arm(
                    "failed_aggression",
                    direction,
                    market,
                    "Fresh large aggressive execution met opposing absorption; subsequent >=2bps reversal confirmed.",
                )
        for wall in market["walls"]:
            executed = wall.get("traded_at_level_usd") or 0
            if (
                wall["persistence_s"] >= 30
                and executed >= 25000
                and (wall.get("observed_refill_usd") or 0) >= 0.5 * executed
            ):
                direction = 1 if wall["side"] == "bid" else -1
                self._arm(
                    "wall_defense",
                    direction,
                    market,
                    "Persistent wall received >=$25k executions with >=50% sampled refill; subsequent >=2bps defense confirmed.",
                    wall_side=wall["side"],
                    wall_price=wall["price"],
                )
        if ctx:
            source_time = context["updated_at"]
            if not self.context_history or source_time > self.context_history[-1][0]:
                self.context_history.append((source_time, ctx["open_interest_btc"]))
            old = next(
                (row for row in reversed(self.context_history) if now - row[0] >= 300),
                None,
            )
            # Bounded historical comparison, never infer growth across an outage.
            if (
                old
                and now - old[0] <= 600
                and old[1] > 0
                and ctx["open_interest_btc"] / old[1] - 1 >= 0.005
            ):
                direction = -1 if funding > 0 else 1
                if abs(funding) >= 0.0001 and previous_mid:
                    excursion = -direction * (market["mid"] / previous_mid - 1) * 10000
                    if excursion >= 5:
                        self._arm(
                            "crowded_failure",
                            direction,
                            market,
                            "Funding/OI crowding followed by >=5bps excursion and later failure through its pre-break level.",
                            anchor=previous_mid,
                            ttl=180,
                        )
        return events

    def _arm(self, kind, direction, market, reason, **extra):
        self.pending.setdefault(
            (kind, direction),
            dict(
                armed_at=market["sampled_at"],
                anchor=market["mid"],
                ttl=120,
                reason=reason,
            )
            | extra,
        )
