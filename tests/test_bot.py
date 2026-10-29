"""Trading loop behaviour with a mocked exchange: startup, breaker, recovery, strategy cycle."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src import bot as bot_module
from src.bot import StartupBlocked, TradingBot
from src.settings import Settings
from src.strategy.engine import latest_closed_open

HOUR = 3_600_000
FILLED = dict(status='ok', response=dict(data=dict(statuses=[dict(filled=dict(totalSz='0.01', avgPx='100', oid=1))])))
RESTING = dict(status='ok', response=dict(data=dict(statuses=[dict(resting=dict(oid=9))])))


def position(coin='BTC', szi='0.01', entry='100'):
    return dict(position=dict(coin=coin, szi=szi, entryPx=entry, positionValue='1', unrealizedPnl='0'))


def hourly(closes, now):
    start = latest_closed_open(int(now * 1000), HOUR) - (len(closes) - 1) * HOUR
    rows = []
    for k, close in enumerate(closes):
        open_ = closes[k - 1] if k else close
        rows.append(dict(t=start + k * HOUR, o=open_, h=max(open_, close) * 1.002, l=min(open_, close) * 0.998,
                         c=close, v=1))
    return rows


class BotHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = Mock()
        self.client.testnet = True
        self.client.address = '0xmaster'
        self.client.get_positions.return_value = []
        self.client.get_open_orders.return_value = []
        self.client.get_account_snapshot.side_effect = lambda: dict(equity=1000.0, unrealized_pnl=0.0,
                                                                    timestamp=time.time(), available=1000.0)
        self.client.bbo_age.return_value = 1
        self.client.get_cached_bbo.return_value = {'bid': {'px': '101.4'}, 'ask': {'px': '101.6'}}
        self.client.get_audit_bbo.return_value = (None, 0)
        self.client.round_size.side_effect = lambda coin, size: round(size, 4)
        self.client.round_price.side_effect = lambda coin, px: round(px, 2)
        self.client.get_sz_decimals.return_value = 4
        settings = Settings(coins=['BTC'], strategy='donchian', strategy_params=dict(entry=20, exit=10, atr=14),
                            risk_per_trade=0.01, cooldown_hours=1)
        self.bot = TradingBot(self.client, settings, data_dir=Path(self.tmp.name))
        self.bot.engine.settle_ms = 0

    def tearDown(self):
        self.tmp.cleanup()


class StartupTests(BotHarness):
    def test_transient_startup_errors_retry_instead_of_exiting(self):
        self.bot.running = True
        calls = []

        def init():
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionError('exchange unreachable')
        with patch.object(self.bot, '_init_exchange', side_effect=init), \
                patch.object(self.bot, '_subscribe_feeds'), patch.object(bot_module.time, 'sleep') as sleep:
            self.bot._startup()
        self.assertEqual(len(calls), 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5, 10])
        self.assertEqual(self.bot.startup_status, 'Ready')

    def test_unapproved_api_wallet_blocks_visibly_without_exiting(self):
        self.client.audit_urls.return_value = dict(info_rest='a', exchange_rest='a', info_ok=True, exchange_ok=True)
        self.client.preflight_check_agent.return_value = dict(agent_registered=False, agent_address='0xagent')
        with self.assertRaises(StartupBlocked):
            self.bot._init_exchange()
        self.bot.running = True
        attempts = []

        def blocked():
            attempts.append(1)
            if len(attempts) == 2:
                self.bot.running = False
            raise StartupBlocked('API wallet not approved')
        with patch.object(self.bot, '_init_exchange', side_effect=blocked), patch.object(bot_module.time, 'sleep'):
            self.bot._startup()
        self.assertIn('Blocked: API wallet not approved', self.bot.startup_status)

    def test_unlisted_coins_are_skipped_not_fatal(self):
        bot = TradingBot(self.client, Settings(coins=['BTC', 'NOPE']), data_dir=Path(self.tmp.name))
        self.client.audit_urls.return_value = dict(info_rest='a', exchange_rest='a', info_ok=True, exchange_ok=True)
        self.client.preflight_check_agent.return_value = dict(agent_registered=True, agent_address='0xagent')
        self.client.info.user_fees.return_value = dict(userAddRate='0.0001', userCrossRate='0.0004')
        self.client.tradable.side_effect = lambda coin: coin == 'BTC'
        self.client.get_fills.return_value = []
        self.client.max_leverage.return_value = 40
        bot._init_exchange()
        self.assertEqual(bot.coins, ['BTC'])
        self.client.set_leverage.assert_called_with('BTC', 10, cross=True)


class BreakerTests(BotHarness):
    def trip(self):
        self.bot.risk_manager.update_equity(1000)
        self.bot.risk_manager.update_equity(940)
        self.assertTrue(self.bot.risk_manager.state.halted)

    def test_halted_tick_flattens_only_exposed_coins_and_never_trades(self):
        self.trip()
        stop = dict(coin='BTC', oid=2, reduceOnly=True, side='A', sz='0.01', orderType='Stop Market', triggerPx='95')
        entry = dict(coin='ETH', oid=1, reduceOnly=False, side='B', sz='1', orderType='Limit')
        # enumerate, close: live, close: after IOC, confirmation
        self.client.get_positions.side_effect = [[position()], [position()], [], []]
        self.client.get_open_orders.side_effect = [[stop, entry], []]
        self.client.place_ioc.return_value = FILLED
        with patch.object(self.bot, '_strategy_cycle') as strategy:
            self.bot._last_equity_fetch = time.time()
            self.bot._tick()
        strategy.assert_not_called()
        self.client.cancel_order.assert_called_once_with('ETH', 1)  # The BTC stop stays until flat.
        self.client.cancel_all_orders.assert_called_once_with('BTC')
        self.assertTrue(self.client.place_ioc.call_args.kwargs['reduce_only'])
        self.assertIn('Confirmed flat', self.bot.halt_cleanup_status)
        self.assertTrue(self.bot.risk_manager.state.halted)  # Cooldown has not elapsed.

    def test_failed_breaker_close_keeps_the_stop(self):
        self.trip()
        stop = dict(coin='BTC', oid=2, reduceOnly=True, side='A', sz='0.01', orderType='Stop Market', triggerPx='95')
        self.client.get_positions.return_value = [position()]
        self.client.get_open_orders.return_value = [stop]
        self.client.place_ioc.side_effect = RuntimeError('thin book')
        self.client.close_position.side_effect = RuntimeError('thin book')
        with self.assertLogs('src.bot', level='ERROR'):
            self.bot._breaker_cycle(time.time())
        self.client.cancel_order.assert_not_called()
        self.client.cancel_all_orders.assert_not_called()
        self.client.close_position.assert_called_once_with('BTC')

    def test_flat_account_does_not_spam_close_requests(self):
        self.trip()
        self.bot._breaker_cycle(time.time())
        self.client.place_ioc.assert_not_called()
        self.client.close_position.assert_not_called()
        self.client.cancel_all_orders.assert_not_called()

    def test_breaker_resets_after_cooldown_once_flat(self):
        self.trip()
        self.bot.risk_manager.state.cooldown_until = time.time() - 1
        self.bot.risk_manager.update_equity(940)
        self.bot._breaker_cycle(time.time())
        self.assertFalse(self.bot.risk_manager.state.halted)
        self.assertEqual(self.bot.risk_manager.state.peak_equity, 940)
        self.assertIn('trading resumed', self.bot.halt_cleanup_status)

    def test_breaker_never_resets_while_exposure_remains(self):
        self.trip()
        self.bot.risk_manager.state.cooldown_until = time.time() - 1
        self.client.get_positions.return_value = [position()]
        self.client.place_ioc.side_effect = RuntimeError('exchange down')
        self.client.close_position.side_effect = RuntimeError('exchange down')
        with self.assertLogs('src.bot', level='ERROR'):
            self.bot._breaker_cycle(time.time())
        self.assertTrue(self.bot.risk_manager.state.halted)
        self.assertIn('retrying', self.bot.halt_cleanup_status)


class RecoveryTests(BotHarness):
    def healthy(self):
        self.bot.risk_manager.update_equity(1000)
        self.bot.account_snapshot = dict(equity=1000)
        self.bot.exchange_snapshot = dict(positions=[], orders=[], time=time.time(), ok=True)

    def cycle(self, t):
        """One recovery check at simulated time ``t`` with reads refreshed as the loop does."""
        self.bot.exchange_snapshot['time'] = t
        self.bot.risk_manager.state.equity_updated_at = t
        self.bot._recovery_cycle(t)

    def test_three_spaced_healthy_checks_resume_with_protected_positions(self):
        self.healthy()
        self.bot.risk_manager.pause_execution('network')
        self.bot.risk_manager.state.pause_until = 0
        now = time.time()
        self.cycle(now)
        self.cycle(now + 5)  # Checks closer than 15s apart do not count.
        self.assertEqual(self.bot._recovery_checks, 1)
        self.cycle(now + 15)
        self.assertTrue(self.bot.risk_manager.state.execution_paused)
        self.cycle(now + 30)
        self.assertFalse(self.bot.risk_manager.state.execution_paused)
        self.client.close_position.assert_not_called()

    def test_unhealthy_check_resets_the_sequence(self):
        self.healthy()
        self.bot.risk_manager.pause_execution('network')
        self.bot.risk_manager.state.pause_until = 0
        now = time.time()
        self.cycle(now)
        self.cycle(now + 15)
        self.client.bbo_age.return_value = 30
        self.cycle(now + 30)
        self.assertEqual(self.bot._recovery_checks, 0)
        self.client.bbo_age.return_value = 1
        self.bot._reconcile_problems = ['BTC protection could not be placed']
        self.cycle(now + 45)
        self.assertEqual(self.bot._recovery_checks, 0)
        self.assertTrue(self.bot.risk_manager.state.execution_paused)

    def test_paused_bot_keeps_positions_protected_instead_of_liquidating(self):
        self.bot.risk_manager.update_equity(1000)
        self.bot.risk_manager.pause_execution('order outcome unknown')
        self.client.get_positions.return_value = [position()]
        self.client.place_stop.return_value = RESTING
        self.bot._last_equity_fetch = time.time()
        with patch.object(self.bot, '_strategy_cycle'):
            self.bot._tick()
        self.client.place_stop.assert_called_once()
        self.client.place_ioc.assert_not_called()
        self.client.close_position.assert_not_called()

    def test_repeatedly_unprotectable_position_is_closed(self):
        self.bot.risk_manager.update_equity(1000)
        self.bot._positions = {'BTC': dict(side=1, size=0.01, entry_px=100.0, value=1.0)}
        self.bot._orders = []
        self.client.place_stop.return_value = dict(status='err', response='rejected')
        self.client.get_positions.side_effect = [[position()], []]
        self.client.place_ioc.return_value = FILLED
        self.bot._reconcile(time.time())
        self.client.place_ioc.assert_not_called()
        self.bot._reconcile(time.time())
        self.assertTrue(self.client.place_ioc.call_args.kwargs['reduce_only'])
        self.assertTrue(self.bot.risk_manager.state.execution_paused)


def bar_close_now(offset=10):
    """A moment just after the latest hourly close (live entries never act on stale bars)."""
    return (time.time() // 3600) * 3600 + offset


class StrategyCycleTests(BotHarness):
    def test_bar_close_breakout_enters_and_records_reason(self):
        self.bot.risk_manager.update_equity(1000)
        now = bar_close_now()
        self.client.get_closed_bars.return_value = hourly([100.0] * 40 + [100.5, 101.5], now)
        self.client.get_positions.side_effect = [[], [position(entry='101.6')]]
        self.client.place_ioc.return_value = FILLED
        self.client.place_stop.return_value = RESTING
        self.bot._strategy_cycle(now)
        self.client.place_ioc.assert_called_once()
        self.client.place_stop.assert_called_once()
        self.assertIsNotNone(self.bot.engine.position('BTC'))
        self.assertIn('entered', self.bot.engine.state['BTC']['reason'])
        self.assertFalse(self.bot.engine.due('BTC', now))

    def test_simultaneous_signals_respect_position_cap(self):
        settings = Settings(coins=['BTC', 'ETH'], strategy='donchian', strategy_params=dict(entry=20, exit=10, atr=14),
                            risk_per_trade=0.01, max_positions=1)
        bot = TradingBot(self.client, settings, data_dir=Path(self.tmp.name) / 'two')
        bot.engine.settle_ms = 0
        bot.risk_manager.update_equity(1000)
        now = bar_close_now()
        self.client.get_closed_bars.return_value = hourly([100.0] * 40 + [100.5, 101.5], now)
        held = []
        self.client.get_positions.side_effect = lambda: list(held)
        self.client.place_stop.return_value = RESTING

        def fill(coin, *args, **kwargs):
            held.append(position(coin=coin, entry='101.6'))
            return FILLED
        self.client.place_ioc.side_effect = fill
        bot._strategy_cycle(now)
        self.assertEqual(self.client.place_ioc.call_count, 1)
        self.assertIn('Maximum open positions', bot.engine.state['ETH']['reason'])

    def test_blocked_entry_reason_is_visible(self):
        self.bot.risk_manager.update_equity(1000)
        self.bot.risk_manager.sync_open_positions(5)
        now = bar_close_now()
        self.client.get_closed_bars.return_value = hourly([100.0] * 40 + [100.5, 101.5], now)
        self.client.get_positions.return_value = []
        self.client.get_positions.side_effect = None
        with patch.object(self.bot, '_refresh_exchange', return_value=True):
            self.bot._positions = {}
            self.bot._strategy_cycle(now)
        self.client.place_ioc.assert_not_called()
        self.assertIn('Maximum open positions', self.bot.engine.state['BTC']['reason'])
        self.assertIn('Maximum open positions', self.bot.strategy_status()['reason'])

    def test_stale_signal_bar_never_opens_a_position(self):
        self.bot.risk_manager.update_equity(1000)
        now = bar_close_now(offset=1800)  # Bot came back half an hour after the close.
        self.client.get_closed_bars.return_value = hourly([100.0] * 40 + [100.5, 101.5], now)
        self.bot._strategy_cycle(now)
        self.client.place_ioc.assert_not_called()
        self.assertIn('no late entry', self.bot.engine.state['BTC']['reason'])

    def test_reversal_rereads_exposure_before_the_opposite_entry(self):
        settings = Settings(coins=['BTC'], strategy='ema_trend', strategy_params=dict(fast=5, slow=20, atr=5),
                            risk_per_trade=0.01, max_positions=1)
        bot = TradingBot(self.client, settings, data_dir=Path(self.tmp.name) / 'rev')
        bot.engine.settle_ms = 0
        bot.risk_manager.update_equity(1000)
        now = bar_close_now()
        closes = [100 + k * 0.1 for k in range(150)] + [100 - k for k in range(1, 30)]
        self.client.get_closed_bars.return_value = hourly(closes, now)
        held = [position(szi='0.01', entry='110')]
        self.client.get_positions.side_effect = lambda: list(held)
        self.client.get_cached_bbo.return_value = {'bid': {'px': '71.9'}, 'ask': {'px': '72.1'}}
        self.client.place_stop.return_value = RESTING

        def trade(coin, is_buy, size, price, reduce_only=False):
            held.clear()
            if not reduce_only:
                held.append(position(szi='-0.01', entry='72'))
            return FILLED
        self.client.place_ioc.side_effect = trade
        bot._refresh_exchange(now)
        bot.engine.opened('BTC', 1, 110.0, 60.0, when_ms=int(now * 1000) - 10 * HOUR)
        bot._strategy_cycle(now)
        self.assertEqual([c.kwargs.get('reduce_only', False) for c in self.client.place_ioc.call_args_list],
                         [True, False])
        self.assertEqual(bot.engine.position('BTC').side, -1)

    def test_malformed_candle_on_one_coin_does_not_stall_others(self):
        settings = Settings(coins=['BTC', 'ETH'], strategy='donchian', strategy_params=dict(entry=20, exit=10, atr=14))
        bot = TradingBot(self.client, settings, data_dir=Path(self.tmp.name) / 'bad')
        bot.engine.settle_ms = 0
        now = bar_close_now()
        good = hourly([100.0] * 60, now)
        bad = [dict(r) for r in good]
        bad[-3]['c'] = None
        self.client.get_closed_bars.side_effect = lambda coin, *a: bad if coin == 'BTC' else good
        bot._strategy_cycle(now)
        self.assertIn('Malformed', bot.engine.state['BTC']['reason'])
        self.assertEqual(bot.engine.state['ETH']['last_bar'], good[-1]['t'])

    def test_unavailable_bars_or_snapshot_defer_without_trading(self):
        now = time.time()
        self.client.get_closed_bars.side_effect = TimeoutError()
        self.bot._strategy_cycle(now)
        self.assertIn('Bar history unavailable', self.bot.engine.state['BTC']['reason'])
        self.assertFalse(self.bot.engine.due('BTC', now + 1))
        self.client.get_positions.side_effect = TimeoutError()
        self.bot._strategy_cycle(now + 600)
        self.assertEqual(self.bot.engine.state['BTC']['reason'], 'Exchange snapshot unavailable')
        self.client.place_ioc.assert_not_called()

    def test_fills_are_deduplicated_and_recorded(self):
        fill = dict(coin='BTC', tid=7, time=int(time.time() * 1000), px='100', sz='0.01', side='B',
                    closedPnl='0', fee='0.01', dir='Open Long')
        self.bot._on_fill([fill, fill])
        self.bot._on_fill([fill])
        self.assertEqual(len(self.bot.ledger.fills(10)), 1)
        self.assertAlmostEqual(self.bot.risk_manager.state.daily_pnl, -0.01)
        self.assertTrue(self.bot._snapshot_dirty)


if __name__ == '__main__':
    unittest.main()
