import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from src.learning.execution import ExecutionJournal
from src.learning.accounting import AccountAudit
from src.learning.funding import FundingSync
from src.learning.ledger import FillLedger
from src.learning.quality import QualityAudit
from src.exchange.hyperliquid import HyperliquidClient
from src.storage import transaction


class AccountAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.journal = ExecutionJournal(self.root / "execution.sqlite")
        self.ledger = FillLedger(self.root / "ledger.sqlite")
        self.funding = FundingSync(self.root / "quality.sqlite", "public", 1000000)
        self.audit = AccountAudit(
            self.journal.path, self.ledger, self.funding.path, "public"
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_intent_is_durable_before_submission_and_roles_use_exact_ids(self):
        c = HyperliquidClient.__new__(HyperliquidClient)
        c.execution_journal = self.journal

        def send():
            self.assertEqual(
                ExecutionJournal(self.journal.path).summary()["unresolved_submissions"],
                1,
            )
            return dict(
                status="ok",
                response=dict(data=dict(statuses=[dict(resting=dict(oid=123))])),
            )

        c._submit_audited(
            "recovery", "BTC", {"size": 0.1}, send, ("recovery_stop_loss_order",)
        )
        self.assertEqual(self.journal.links()[0]["oid"], "123")
        self.assertEqual(self.journal.links()[0]["role"], "recovery_stop_loss_order")
        self.assertEqual(self.journal.summary()["unresolved_submissions"], 0)

    def test_ambiguous_submission_never_retries(self):
        c = HyperliquidClient.__new__(HyperliquidClient)
        c.execution_journal = self.journal
        action = Mock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError):
            c._submit_audited("entry", "BTC", {}, action, entry=True)
        action.assert_called_once()
        self.assertEqual(self.journal.summary()["unresolved_submissions"], 1)
        self.assertEqual(self.journal.summary()["recent"][0]["outcome"], "TimeoutError")

    def test_failed_intent_blocks_entry_but_never_blocks_close(self):
        c = HyperliquidClient.__new__(HyperliquidClient)
        c.execution_journal = Mock()
        c.execution_journal.begin.side_effect = OSError()
        action = Mock(return_value=None)
        with self.assertRaises(OSError):
            c._submit_audited("entry", "BTC", {}, action, entry=True)
        action.assert_not_called()
        with self.assertLogs("src.exchange.hyperliquid", level="ERROR"):
            c._submit_audited("close", "BTC", {}, action)
        action.assert_called_once()

    def test_nested_order_updates_are_idempotent_and_preserved(self):
        event = dict(
            order=dict(coin="BTC", oid=123, side="A"),
            status="canceled",
            statusTimestamp=1000,
        )
        self.assertTrue(self.journal.event(event))
        self.assertFalse(self.journal.event(event))
        self.assertEqual(len(self.journal.summary()["events"]), 1)
        self.assertFalse(self.journal.event(dict(status="canceled")))

    def sample(self, t, equity=1000, unrealized=0):
        self.audit.sample(dict(timestamp=t, equity=equity, unrealized_pnl=unrealized))

    def test_equity_bridge_components_and_baseline_survive_restart(self):
        self.sample(1000)
        self.sample(1120, 1001.8, 1)
        f = dict(
            coin="BTC",
            tid=1,
            time=1050000,
            px="100",
            sz="1",
            side="B",
            fee=".2",
            closedPnl="2",
            feeToken="USDC",
        )

        def post(p):
            if p["type"] == "userFillsByTime":
                return [f]
            return [dict(time=1060000, delta=dict(type="withdraw", usdc="1"))]

        self.audit.step(post, 1200)
        with transaction(self.funding.path) as db:
            db.execute("UPDATE funding_state SET through_ms=1200000")
            db.execute("INSERT INTO funding VALUES ('f',1070000,'BTC',-0.0,'{}')")
        report = self.audit.summary()
        self.assertEqual(report["status"], "within_tolerance")
        self.assertAlmostEqual(report["unexplained"], 0)
        self.assertEqual(report["known_cash_movements"], -1)
        self.audit = AccountAudit(
            self.journal.path, self.ledger, self.funding.path, "public"
        )
        self.sample(1240, 999)
        self.assertEqual(self.audit.summary()["baseline_equity"], 1000)

    def test_unknown_movement_and_missing_funding_never_assumed_zero(self):
        self.sample(1000)
        self.sample(1120)
        self.audit.step(
            lambda p: (
                []
                if p["type"] == "userFillsByTime"
                else [dict(time=1060000, delta=dict(type="mystery"))]
            ),
            1200,
        )
        self.assertEqual(self.audit.summary()["status"], "warming_up")
        with transaction(self.funding.path) as db:
            db.execute("UPDATE funding_state SET through_ms=1200000")
        report = self.audit.summary()
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["unknown_movements"], 1)

    def test_capped_or_malformed_history_does_not_advance_coverage(self):
        self.sample(1000)
        with self.assertRaises(ValueError):
            self.audit.step(lambda p: [{}] * 500, 1200)
        with transaction(self.journal.path) as db:
            self.assertEqual(
                db.execute(
                    "SELECT through FROM account_coverage WHERE kind='fills'"
                ).fetchone()[0],
                1000000,
            )
        with self.assertRaises(ValueError):
            self.audit.step(lambda p: [dict(time=1)], 1200)

    def test_recovery_exit_attribution_does_not_invent_entry_context(self):
        q = QualityAudit(self.root / "quality2.sqlite")
        fills = [
            dict(
                coin="BTC",
                tid=1,
                oid=1,
                time=1000,
                px="100",
                sz="1",
                side="B",
                fee="0",
                closedPnl="0",
                startPosition="0",
            ),
            dict(
                coin="BTC",
                tid=2,
                oid=2,
                time=2000,
                px="101",
                sz="1",
                side="A",
                fee="0",
                closedPnl="1",
                startPosition="1",
            ),
        ]
        report = q.summary(
            fills,
            [
                dict(coin="BTC", oid="1", role="entry"),
                dict(coin="BTC", oid="2", role="emergency_close_order"),
            ],
        )
        self.assertEqual(report["recent"][0]["exit_reason"], "emergency_close_order")
        self.assertEqual(report["recent"][0]["regime"], "unknown")
        self.assertEqual(report["execution"]["n"], 0)


class AccountLevelRejectionTests(unittest.TestCase):
    def test_string_error_response_is_recorded_not_raised(self):
        import tempfile
        from pathlib import Path
        from src.learning.execution import ExecutionJournal
        from src.learning.quality import QualityAudit
        with tempfile.TemporaryDirectory() as d:
            journal = ExecutionJournal(Path(d) / 'execution.sqlite')
            ident = journal.begin('ioc_entry', 'BTC', {})
            journal.finish(ident, 'BTC', {'status': 'err', 'response': 'User or API Wallet does not exist.'}, ('entry',))
            summary = journal.summary()
            self.assertEqual(summary['unresolved_submissions'], 0)
            self.assertIn('API Wallet', summary['recent'][0]['outcome'])
        self.assertEqual(QualityAudit.order_ids({'status': 'err', 'response': 'rejected'}), [])
        self.assertEqual(QualityAudit.order_ids(None), [])
