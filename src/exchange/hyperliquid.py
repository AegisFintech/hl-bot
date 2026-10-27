import json
import logging
import time
import threading
import math
from decimal import Decimal, ROUND_DOWN
from collections import defaultdict
from src.market.candles import merge_bars, coverage

import eth_account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

log = logging.getLogger(__name__)


class HyperliquidClient:

    def __init__(self, master_account: str, api_private_key: str, testnet: bool = True):
        self.testnet = testnet
        self.base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
        self.wallet = eth_account.Account.from_key(api_private_key)
        self.master_account = master_account
        self.address = self.master_account
        self.info = Info(self.base_url, skip_ws=True, timeout=10)
        self.exchange = Exchange(self.wallet, self.base_url, account_address=self.master_account, timeout=10)
        self._ws_info = None
        self._ws_subscriptions = []
        self._subscriptions = {}
        self._orderbook = {}
        self._bbo = {}
        self._candles = defaultdict(list)
        self._trades = defaultdict(list)
        self._positions = {}
        self._fills = []
        self._lock = threading.Lock()
        self._ws_monitor = None
        self._reconnect_callback = None
        self._meta_cache: dict | None = None
        self._meta_cache_time: float = 0.0
        self._mid_cache: dict[str, tuple[float, float]] = {}
        self._abstraction = None
        self._bbo_times = {}
        self._candle_health = {}

    def audit_urls(self) -> dict:
        info_url = self.info.base_url
        exchange_url = self.exchange.base_url
        ws_url = None
        if self._ws_info and self._ws_info.ws_manager:
            ws_url = self._ws_info.ws_manager.ws.url
        expected_rest = constants.TESTNET_API_URL if self.testnet else constants.MAINNET_API_URL
        expected_ws = "wss" + expected_rest[len("https"):] + "/ws"
        return {
            "info_rest": info_url,
            "exchange_rest": exchange_url,
            "ws": ws_url,
            "expected_rest": expected_rest,
            "expected_ws": expected_ws,
            "info_ok": info_url == expected_rest,
            "exchange_ok": exchange_url == expected_rest,
            "ws_ok": ws_url is None or ws_url == expected_ws,
        }

    def preflight_check_agent(self) -> dict:
        extra_agents = self.info.extra_agents(self.master_account)
        sub_accounts = self.info.query_sub_accounts(self.master_account)
        agent_addr = self.wallet.address.lower()
        agent_found = False
        for agent in extra_agents:
            if agent.get("address", "").lower() == agent_addr:
                agent_found = True
                break
        return {
            "extra_agents_raw": extra_agents,
            "sub_accounts_raw": sub_accounts,
            "agent_address": self.wallet.address,
            "agent_registered": agent_found,
        }

    def get_meta(self) -> dict:
        if self._meta_cache is None or time.time() - self._meta_cache_time > 300:
            self._meta_cache = self.info.meta()
            self._meta_cache_time = time.time()
        return self._meta_cache

    def get_sz_decimals(self, coin: str) -> int:
        meta = self.get_meta()
        for asset in meta["universe"]:
            if asset["name"] == coin:
                return asset["szDecimals"]
        raise ValueError(f"Unknown coin: {coin}")

    def round_size(self, coin: str, size: float) -> float:
        decimals = self.get_sz_decimals(coin)
        value = Decimal(str(size))
        if not value.is_finite() or value < 0:
            raise ValueError("Invalid order size")
        return float(value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN))

    def round_price(self, coin: str, price: float) -> float:
        tick = self.get_tick_size(coin)
        return round(round(price / tick) * tick, 8)

    def get_tick_size(self, coin: str) -> float:
        mid = self.get_mid_price(coin)
        if mid >= 10000:
            return 1.0
        elif mid >= 1000:
            return 0.1
        elif mid >= 100:
            return 0.01
        elif mid >= 1:
            return 0.001
        else:
            return 0.0001

    def get_mid_price(self, coin: str) -> float:
        cached = self._mid_cache.get(coin)
        if cached and time.time() - cached[1] < 2.0:
            return cached[0]
        mids = self.info.all_mids()
        mid = float(mids[coin])
        self._mid_cache[coin] = (mid, time.time())
        return mid

    def get_l2_snapshot(self, coin: str) -> dict:
        return self.info.l2_snapshot(coin)

    def get_candles(self, coin: str, interval: str, lookback_ms: int) -> list:
        now = int(time.time() * 1000)
        start = now - lookback_ms
        return self.info.candles_snapshot(coin, interval, start, now)

    def get_user_state(self) -> dict:
        return self.info.user_state(self.address)

    def get_spot_user_state(self) -> dict:
        return self.info.spot_user_state(self.address)

    def get_spot_usdc_balance(self) -> float:
        state = self.get_spot_user_state()
        for b in state.get("balances", []):
            if b["coin"] == "USDC":
                return float(b["total"])
        return 0.0

    def get_positions(self) -> list:
        state = self.get_user_state()
        return [p for p in state.get("assetPositions", []) if float(p["position"]["szi"]) != 0]

    def get_open_orders(self) -> list:
        return self.info.frontend_open_orders(self.address)

    def get_fills(self, limit: int = 50) -> list:
        return self.info.user_fills(self.address)[:limit]

    def get_perps_account_value(self) -> float:
        state = self.get_user_state()
        return float(state.get("marginSummary", {}).get("accountValue", 0))

    def get_available_to_trade(self) -> float:
        spot_state = self.get_spot_user_state()
        for token_id, amount in spot_state.get("tokenToAvailableAfterMaintenance", []):
            if token_id == 0:
                return float(amount)
        return 0.0

    def get_account_snapshot(self) -> dict:
        if self._abstraction is None:
            self._abstraction = self.info.post('/info', {'type': 'userAbstraction', 'user': self.address})
        state = self.get_user_state()
        spot = self.get_spot_user_state()
        usdc = next((float(b['total']) for b in spot.get('balances', []) if b['coin'] == 'USDC'), 0.0)
        unrealized = sum(float(p['position'].get('unrealizedPnl', 0)) for p in state.get('assetPositions', []))
        perps = float(state.get('marginSummary', {}).get('accountValue', 0))
        if self._abstraction == 'unifiedAccount':
            equity = usdc + unrealized
            available = next((float(v) for token, v in spot.get('tokenToAvailableAfterMaintenance', []) if token == 0), 0)
        elif self._abstraction in ('default', 'disabled', 'standard'):
            equity = perps + usdc
            available = float(state.get('withdrawable', 0))
        else:
            raise ValueError(f'Unsupported account abstraction: {self._abstraction}')
        return dict(equity=equity, available=available, spot_usdc=usdc, perps_account_value=perps,
                    unrealized_pnl=unrealized, margin_used=float(state.get('marginSummary', {}).get('totalMarginUsed',0)),
                    mode=self._abstraction, positions=state.get('assetPositions', []), timestamp=time.time())

    def get_account_value(self) -> float:
        return self.get_account_snapshot()['equity']

    def get_audit_bbo(self, coin):
        """Atomic quote and local receipt time; no network reads."""
        with self._lock:
            return self._bbo.get(coin), self._bbo_times.get(coin, 0)

    def bbo_age(self, coin):
        return time.time() - self._bbo_times.get(coin, 0)

    def transfer_spot_to_perps(self, amount_usd: float) -> dict:
        return self.exchange.usd_class_transfer(amount_usd, True)

    # -- Trading --

    def place_maker_order(self, coin: str, is_buy: bool, size: float, price: float) -> dict:
        size = self.round_size(coin, size)
        return self.exchange.order(coin, is_buy, size, price, {"limit": {"tif": "Alo"}})

    def place_limit_order(self, coin: str, is_buy: bool, size: float, price: float) -> dict:
        size = self.round_size(coin, size)
        return self.exchange.order(coin, is_buy, size, price, {"limit": {"tif": "Gtc"}})

    def place_market_order(self, coin: str, is_buy: bool, size: float, slippage: float = 0.01) -> dict:
        size = self.round_size(coin, size)
        return self.exchange.market_open(coin, is_buy, size, None, slippage)

    def place_order_with_tpsl(self, coin: str, is_buy: bool, size: float, entry_price: float,
                               tp_price: float, sl_price: float, tif: str = "Gtc") -> dict:
        size = self.round_size(coin, size)
        exit_side = not is_buy
        sl_buffer = sl_price * 0.02
        if is_buy:
            sl_limit_px = self.round_price(coin, sl_price - sl_buffer)
        else:
            sl_limit_px = self.round_price(coin, sl_price + sl_buffer)
        orders = [
            {
                "coin": coin, "is_buy": is_buy, "sz": size, "limit_px": entry_price,
                "order_type": {"limit": {"tif": tif}}, "reduce_only": False,
            },
            {
                "coin": coin, "is_buy": exit_side, "sz": size, "limit_px": tp_price,
                "order_type": {"trigger": {"triggerPx": tp_price, "isMarket": False, "tpsl": "tp"}},
                "reduce_only": True,
            },
            {
                "coin": coin, "is_buy": exit_side, "sz": size, "limit_px": sl_limit_px,
                "order_type": {"trigger": {"triggerPx": sl_price, "isMarket": True, "tpsl": "sl"}},
                "reduce_only": True,
            },
        ]
        return self.exchange.bulk_orders(orders, grouping="normalTpsl")

    def cancel_order(self, coin: str, oid: int) -> dict:
        return self.exchange.cancel(coin, oid)

    def cancel_all_orders(self, coin: str) -> list:
        orders = [o for o in self.get_open_orders() if o["coin"] == coin]
        if not orders:
            return []
        cancel_requests = [{"coin": coin, "oid": o["oid"]} for o in orders]
        for i in range(0, len(cancel_requests), 50):
            batch = cancel_requests[i:i + 50]
            self.exchange.bulk_cancel(batch)
        return [{"status": "bulk_cancelled", "count": len(cancel_requests)}]

    def close_position(self, coin: str) -> dict:
        return self.exchange.market_close(coin)

    def place_trigger_orders(self, coin: str, is_buy: bool, size: float,
                             tp_price: float, sl_price: float) -> dict:
        size = self.round_size(coin, size)
        sl_buffer = sl_price * 0.02
        if is_buy:
            sl_limit_px = self.round_price(coin, sl_price + sl_buffer)
        else:
            sl_limit_px = self.round_price(coin, sl_price - sl_buffer)
        orders = [
            {
                "coin": coin, "is_buy": is_buy, "sz": size, "limit_px": tp_price,
                "order_type": {"trigger": {"triggerPx": tp_price, "isMarket": False, "tpsl": "tp"}},
                "reduce_only": True,
            },
            {
                "coin": coin, "is_buy": is_buy, "sz": size, "limit_px": sl_limit_px,
                "order_type": {"trigger": {"triggerPx": sl_price, "isMarket": True, "tpsl": "sl"}},
                "reduce_only": True,
            },
        ]
        return self.exchange.bulk_orders(orders, grouping="na")

    def set_leverage(self, coin: str, leverage: int, cross: bool = True) -> dict:
        return self.exchange.update_leverage(leverage, coin, is_cross=cross)

    # -- WebSocket subscriptions --

    def _get_ws_info(self):
        if self._ws_info is None:
            self._ws_info = Info(self.base_url, skip_ws=False)
            self._start_ws_monitor()
        return self._ws_info

    def _start_ws_monitor(self):
        if self._ws_monitor and self._ws_monitor.is_alive():
            return
        self._ws_monitor = threading.Thread(target=self._ws_monitor_loop, daemon=True)
        self._ws_monitor.start()

    def _ws_monitor_loop(self):
        while True:
            time.sleep(30)
            try:
                if self._ws_info and self._ws_info.ws_manager:
                    ws = self._ws_info.ws_manager.ws
                    if not ws.keep_running:
                        log.warning("WebSocket disconnected — reconnecting...")
                        self._reconnect_ws()
            except Exception as e:
                log.error("WS monitor error: %s", e)

    def _reconnect_ws(self):
        try:
            if self._ws_info and self._ws_info.ws_manager:
                try:
                    self._ws_info.ws_manager.stop()
                except Exception:
                    pass
            with self._lock:
                self._bbo_times.clear()  # Old connection quotes cannot remain eligible.
            self._ws_info = Info(self.base_url, skip_ws=False)
            for sub, handler in self._ws_subscriptions:
                self._ws_info.subscribe(dict(sub), handler)
            log.info("WebSocket reconnected, %d subscriptions restored", len(self._ws_subscriptions))
            if self._reconnect_callback:
                try:
                    self._reconnect_callback()
                except Exception as e:
                    log.error("Reconnect callback error: %s", e)
        except Exception as e:
            log.error("WebSocket reconnect failed: %s", e)

    def set_reconnect_callback(self, callback):
        self._reconnect_callback = callback

    def subscribe_bbo(self, coin: str, callback=None):
        def handler(msg):
            data = msg["data"]
            bbo_arr = data.get("bbo", [])
            if len(bbo_arr) >= 2:
                normalized = {"bid": bbo_arr[0], "ask": bbo_arr[1], "coin": data.get("coin", coin)}
            else:
                normalized = data
            with self._lock:
                self._bbo[coin] = normalized
                self._bbo_times[coin] = time.time()
            if callback:
                callback(normalized)
        sub = {"type": "bbo", "coin": coin}
        self._ws_subscriptions.append((sub, handler))
        self._get_ws_info().subscribe(sub, handler)

    def subscribe_l2(self, coin: str, callback=None):
        def handler(msg):
            with self._lock:
                self._orderbook[coin] = msg["data"]
            if callback:
                callback(msg["data"])
        sub = {"type": "l2Book", "coin": coin}
        self._ws_subscriptions.append((sub, handler))
        self._get_ws_info().subscribe(sub, handler)

    def subscribe_trades(self, coin: str, callback=None):
        def handler(msg):
            with self._lock:
                self._trades[coin] = msg["data"][-100:]
            if callback:
                callback(msg["data"])
        sub = {"type": "trades", "coin": coin}
        self._ws_subscriptions.append((sub, handler))
        self._get_ws_info().subscribe(sub, handler)

    def merge_candles(self, coin, incoming, interval='1m', source='ws', requested_at=None):
        key = f'{coin}_{interval}'
        if source == 'rest':
            # A REST request must not overwrite a newer websocket forming bar.
            cutoff = time.time() if requested_at is None else requested_at
            incoming = [b for b in incoming if int(b.get('t', 0)) + 60000 <= cutoff * 1000]
        with self._lock:
            bars, rejected = merge_bars(self._candles.get(key, []), incoming)
            self._candles[key] = bars
            meta = self._candle_health.setdefault(key, {})
            meta['rejected_updates'] = meta.get('rejected_updates', 0) + rejected
            if rejected:
                meta['integrity_error'] = 'Malformed candle update; waiting for repair'
            elif source == 'rest':
                meta['integrity_error'] = None
                meta['last_repair_at'] = time.time()
                meta['repair_error'] = None
            meta['last_source'] = source

    def candle_health(self, coin, interval='1m'):
        key = f'{coin}_{interval}'
        with self._lock:
            result = coverage(self._candles.get(key, []), time.time())
            result.update(self._candle_health.get(key, {}))
        if result.get('integrity_error'):
            result.update(eligible=False, reason=result['integrity_error'])
        return result

    def subscribe_candles(self, coin: str, interval: str = "1m", callback=None):
        def handler(msg):
            candle = msg['data']
            self.merge_candles(coin, [candle], interval)
            if callback:
                callback(candle)
        sub = {"type": "candle", "coin": coin, "interval": interval}
        self._ws_subscriptions.append((sub, handler))
        self._get_ws_info().subscribe(sub, handler)

    def subscribe_fills(self, callback=None):
        def handler(msg):
            raw = msg.get("data", {}) if isinstance(msg, dict) else {}
            is_snapshot = raw.get("isSnapshot", False) if isinstance(raw, dict) else False
            fills = raw.get("fills", raw) if isinstance(raw, dict) and "fills" in raw else raw
            if not isinstance(fills, list):
                return
            with self._lock:
                self._fills.extend(fills)
                self._fills = self._fills[-500:]
            if callback and not is_snapshot:
                callback(fills)
        sub = {"type": "userFills", "user": self.address}
        self._ws_subscriptions.append((sub, handler))
        self._get_ws_info().subscribe(sub, handler)

    def subscribe_order_updates(self, callback=None):
        def handler(msg):
            if callback:
                callback(msg["data"])
        sub = {"type": "orderUpdates", "user": self.address}
        self._ws_subscriptions.append((sub, handler))
        self._get_ws_info().subscribe(sub, handler)

    # -- Cached data access --

    def get_cached_bbo(self, coin: str) -> dict | None:
        with self._lock:
            return self._bbo.get(coin)

    def get_cached_orderbook(self, coin: str) -> dict | None:
        with self._lock:
            return self._orderbook.get(coin)

    def get_cached_candles(self, coin: str, interval: str = "1m") -> list:
        with self._lock:
            return list(self._candles.get(f"{coin}_{interval}", []))

    def get_cached_trades(self, coin: str) -> list:
        with self._lock:
            return list(self._trades.get(coin, []))

    def get_cached_fills(self) -> list:
        with self._lock:
            return list(self._fills)
