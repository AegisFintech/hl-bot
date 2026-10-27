import copy
import json
import unittest
from pathlib import Path
from src.validation.simulator import simulate
from src.validation.evidence import evaluate, protocol_hash


class SimulationTests(unittest.TestCase):
    def setUp(self):
        p = Path(__file__).resolve().parents[1] / "docs/examples/simulation.json"
        self.example = json.loads(p.read_text())
        self.order = self.example["order"]
        self.events = self.example["events"]
        self.assumptions = self.example["scenarios"]["illustrative_conservative"]

    def test_partial_fill_consumes_queue_and_deducts_costs(self):
        r = simulate(self.order, self.events, self.assumptions)
        self.assertEqual(r["status"], "simulated")
        self.assertEqual(r["filled_size"], 0.25)
        self.assertLess(r["net_usd"], r["gross_usd"])
        self.assertGreater(r["funding_assumption_usd"], 0)

    def test_quote_touch_alone_never_assumed_filled(self):
        r = simulate(
            self.order,
            [e for e in self.events if e["type"] == "quote"],
            self.assumptions,
        )
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(r["filled_size"], 0)

    def test_duplicates_do_not_create_extra_fill_volume(self):
        events = copy.deepcopy(self.events)
        events.insert(2, dict(events[1]))
        self.assertEqual(
            simulate(self.order, events, self.assumptions)["filled_size"], 0.25
        )

    def test_arrival_crossing_is_post_only_rejected(self):
        r = simulate(dict(self.order, limit=101), self.events, self.assumptions)
        self.assertEqual(r["status"], "post_only_rejected")

    def test_quote_gap_or_missing_exit_has_no_profit_result(self):
        bad = copy.deepcopy(self.events)
        bad[-1]["time"] = 1008
        self.assertEqual(
            simulate(self.order, bad, self.assumptions)["status"], "unavailable"
        )
        r = simulate(self.order, self.events[:-1], self.assumptions)
        self.assertNotIn("net_usd", r)

    def test_side_queue_and_latency_change_fills(self):
        events = copy.deepcopy(self.events)
        events[1]["side"] = "buy"
        self.assertEqual(
            simulate(self.order, events, self.assumptions)["status"], "unfilled"
        )
        r = simulate(self.order, self.events, dict(self.assumptions, queue_ahead=2))
        self.assertEqual(r["filled_size"], 0)

    def test_malformed_and_out_of_order_traces_rejected(self):
        events = copy.deepcopy(self.events)
        events[2]["bid"] = float("nan")
        with self.assertRaises(ValueError):
            simulate(self.order, events, self.assumptions)
        with self.assertRaises(ValueError):
            simulate(self.order, list(reversed(self.events)), self.assumptions)


class EvidenceTests(unittest.TestCase):
    def protocol(self):
        return dict(
            version="test-v1",
            locked_at=1,
            training_end=10,
            holdout_start=100,
            holdout_end=200000,
            min_days=2,
            min_episodes=2,
            embargo_s=60,
            trials_attempted=1,
            extra_cost_stress_bps=6,
            execution_stress_reviewed=True,
            trial_inventory_complete=True,
        )

    def rows(self, p):
        return [
            dict(
                id=str(i),
                version=p["version"],
                protocol_hash=protocol_hash(p),
                source="demo_fill",
                opened_at=1000 + i * 86400,
                closed_at=1030 + i * 86400,
                observed_at=1031 + i * 86400,
                net_bps=20,
                funding_included=True,
            )
            for i in range(2)
        ]

    def test_future_observation_cutoff_and_holdout_completion(self):
        p = self.protocol()
        r = evaluate(self.rows(p), p, 1100)
        self.assertEqual(r["included"], 1)
        self.assertEqual(r["status"], "not_ready")
        self.assertFalse(r["automatic_promotion"])

    def test_ready_is_manual_review_only(self):
        p = self.protocol()
        r = evaluate(self.rows(p), p, 200001)
        self.assertEqual(r["status"], "review_ready")
        self.assertFalse(r["automatic_promotion"])

    def test_quote_or_missing_funding_can_never_pass(self):
        p = self.protocol()
        rows = self.rows(p)
        for row in rows:
            row["source"] = "quote"
            row["funding_included"] = False
        r = evaluate(rows, p, 200001)
        self.assertEqual(r["status"], "not_ready")
        self.assertIn("Funding coverage incomplete", r["blockers"])

    def test_duplicate_mixed_or_mutated_cohorts_rejected(self):
        p = self.protocol()
        rows = self.rows(p)
        with self.assertRaises(ValueError):
            evaluate(rows + [rows[0]], p, 200001)
        rows[0]["source"] = "simulation"
        with self.assertRaises(ValueError):
            evaluate(rows, p, 200001)
        p["version"] = "mutated"
        with self.assertRaises(ValueError):
            evaluate(rows, p, 200001)

    def test_overlapping_labels_reduce_episode_count(self):
        p = self.protocol()
        rows = self.rows(p)
        rows.append(
            dict(rows[0], id="extra", opened_at=1010, closed_at=1040, observed_at=1041)
        )
        r = evaluate(rows, p, 200001)
        self.assertEqual(r["included"], 3)
        self.assertEqual(r["nonoverlap_episodes"], 2)

    def test_invalid_embargo_and_cost_stress_rejected(self):
        p = self.protocol()
        p["embargo_s"] = 10
        with self.assertRaises(ValueError):
            evaluate(self.rows(p), p, 200001)
        p = self.protocol()
        p["extra_cost_stress_bps"] = -1
        with self.assertRaises(ValueError):
            evaluate(self.rows(p), p, 200001)


class PortfolioTests(unittest.TestCase):
    def payload(self):
        from datetime import date, timedelta

        days = {
            (date(2026, 1, 1) + timedelta(days=i)).isoformat(): 0.001 * (i % 3 - 1)
            for i in range(35)
        }
        return dict(
            strategies={
                "a": {"daily_returns": days, "evidence_status": "unvalidated"},
                "b": {"daily_returns": dict(days), "evidence_status": "unvalidated"},
            },
            weights={"a": 0.4, "b": 0.4},
            stress_scenarios=[{"name": "joint", "returns": {"a": -0.02, "b": -0.03}}],
            capacity={
                "executable_depth_usd": 100000,
                "order_notional_usd": 100,
                "max_depth_participation": 0.01,
            },
        )

    def test_aligned_only_and_never_approved(self):
        from src.validation.portfolio import review_portfolio

        p = self.payload()
        p["strategies"]["b"]["daily_returns"].pop("2026-01-01")
        r = review_portfolio(p)
        self.assertEqual(r["aligned_days"], 34)
        self.assertEqual(r["excluded_dates"]["a"], 1)
        self.assertFalse(r["approved"])
        self.assertEqual(r["status"], "blocked")
        self.assertAlmostEqual(r["correlations"][0]["correlation"], 1)

    def test_leverage_and_missing_joint_shock_rejected(self):
        from src.validation.portfolio import review_portfolio

        p = self.payload()
        p["weights"]["a"] = 1
        with self.assertRaises(ValueError):
            review_portfolio(p)
        p = self.payload()
        p["stress_scenarios"][0]["returns"].pop("b")
        with self.assertRaises(ValueError):
            review_portfolio(p)

    def test_capacity_and_account_limit_block_review(self):
        from src.validation.portfolio import review_portfolio

        p = self.payload()
        p["capacity"]["order_notional_usd"] = 10000
        p["stress_scenarios"][0]["returns"] = {"a": -0.2, "b": -0.2}
        r = review_portfolio(p)
        self.assertTrue(any("participation" in b for b in r["blockers"]))
        self.assertTrue(any("account limit" in b for b in r["blockers"]))
