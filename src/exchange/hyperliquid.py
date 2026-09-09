import json
import time
import threading
from collections import defaultdict

import eth_account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants


class HyperliquidClient:

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.testnet = testnet
        self.base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
        self.wallet = eth_account.Account.from_key(api_secret)
        self.address = self.wallet.address
        self.info = Info(self.base_url)
        self.exchange = Exchange(self.wallet, self.base_url)
        self._subscriptions = {}
        self._orderbook = {}
        self._bbo = {}
        self._candles = defaultdict(list)
        self._trades = defaultdict(list)
        self._positions = {}
        self._fills = []
        self._lock = threading.Lock()

    def get_meta(self) -> dict:
        return self.info.meta()

    def get_sz_decimals(self, coin: str) -> int:
        meta = self.get_meta()
        for asset in meta["universe"]:
            if asset["name"] == coin:
                return asset["szDecimals"]
        raise ValueError(f"Unknown coin: {coin}")

    def round_size(self, coin: str, size: float) -> float:
        decimals = self.get_sz_decimals(coin)
        return round(size, decimals)

    def get_mid_price(self, coin: str) -> float:
        mids = self.info.all_mids()
        return float(mids[coin])

    def get_l2_snapshot(self, coin: str) -> dict:
        return self.info.l2_snapshot(coin)

    def get_candles(self, coin: str, interval: str, lookback_ms: int) -> list:
        now = int(time.time() * 1000)
        start = now - lookback_ms
        return self.info.candles_snapshot(coin, interval, start, now)

    def get_user_state(self) -> dict:
        return self.info.user_state(self.address)

    def get_positions(self) -> list:
        state = self.get_user_state()
        return [p for p in state.get("assetPositions", []) if float(p["position"]["szi"]) != 0]

    def get_open_orders(self) -> list:
        return self.info.open_orders(self.address)

    def get_fills(self, limit: int = 50) -> list:
        return self.info.user_fills(self.address)[:limit]

    def get_account_value(self) -> float:
        state = self.get_user_state()
        return float(state.get("marginSummary", {}).get("accountValue", 0))

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
                               tp_price: float, sl_price: float) -> dict:
        size = self.round_size(coin, size)
        exit_side = not is_buy
        orders = [
            {
                "coin": coin, "is_buy": is_buy, "sz": size, "limit_px": entry_price,
                "order_type": {"limit": {"tif": "Alo"}}, "reduce_only": False,
            },
            {
                "coin": coin, "is_buy": exit_side, "sz": size, "limit_px": tp_price,
                "order_type": {"trigger": {"triggerPx": tp_price, "isMarket": True, "tpsl": "tp"}},
                "reduce_only": True,
            },
            {
                "coin": coin, "is_buy": exit_side, "sz": size, "limit_px": sl_price,
                "order_type": {"trigger": {"triggerPx": sl_price, "isMarket": True, "tpsl": "sl"}},
                "reduce_only": True,
            },
        ]
        return self.exchange.bulk_orders(orders, grouping="normalTpsl")

    def cancel_order(self, coin: str, oid: int) -> dict:
        return self.exchange.cancel(coin, oid)

    def cancel_all_orders(self, coin: str) -> list:
        results = []
        for order in self.get_open_orders():
            if order["coin"] == coin:
                results.append(self.cancel_order(coin, order["oid"]))
        return results

    def close_position(self, coin: str) -> dict:
        return self.exchange.market_close(coin)

    def set_leverage(self, coin: str, leverage: int, cross: bool = True) -> dict:
        return self.exchange.update_leverage(leverage, coin, is_cross=cross)

    # -- WebSocket subscriptions --

    def subscribe_bbo(self, coin: str, callback=None):
        def handler(msg):
            with self._lock:
                self._bbo[coin] = msg["data"]
            if callback:
                callback(msg["data"])
        self.info.subscribe({"type": "bbo", "coin": coin}, handler)

    def subscribe_l2(self, coin: str, callback=None):
        def handler(msg):
            with self._lock:
                self._orderbook[coin] = msg["data"]
            if callback:
                callback(msg["data"])
        self.info.subscribe({"type": "l2Book", "coin": coin}, handler)

    def subscribe_trades(self, coin: str, callback=None):
        def handler(msg):
            with self._lock:
                self._trades[coin] = msg["data"][-100:]
            if callback:
                callback(msg["data"])
        self.info.subscribe({"type": "trades", "coin": coin}, handler)

    def subscribe_candles(self, coin: str, interval: str = "1m", callback=None):
        def handler(msg):
            with self._lock:
                key = f"{coin}_{interval}"
                candle = msg["data"]
                if self._candles[key] and self._candles[key][-1]["t"] == candle["t"]:
                    self._candles[key][-1] = candle
                else:
                    self._candles[key].append(candle)
                    self._candles[key] = self._candles[key][-500:]
            if callback:
                callback(candle)
        self.info.subscribe({"type": "candle", "coin": coin, "interval": interval}, handler)

    def subscribe_fills(self, callback=None):
        def handler(msg):
            with self._lock:
                self._fills.extend(msg["data"])
                self._fills = self._fills[-500:]
            if callback:
                callback(msg["data"])
        self.info.subscribe({"type": "userFills", "user": self.address}, handler)

    def subscribe_order_updates(self, callback=None):
        def handler(msg):
            if callback:
                callback(msg["data"])
        self.info.subscribe({"type": "orderUpdates", "user": self.address}, handler)

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
