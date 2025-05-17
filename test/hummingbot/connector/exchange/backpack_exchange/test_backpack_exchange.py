import asyncio
import sys
import types
from unittest import TestCase
from unittest.mock import AsyncMock

pandas_stub = types.ModuleType("pandas")
pandas_stub.options = types.SimpleNamespace(display=types.SimpleNamespace(float_format=None))
class DummyDataFrame:
    pass
pandas_stub.DataFrame = DummyDataFrame
sys.modules.setdefault("pandas", pandas_stub)
sys.modules.setdefault("numpy", types.ModuleType("numpy"))
sys.modules.setdefault("hexbytes", types.ModuleType("hexbytes"))
sys.modules["hexbytes"].HexBytes = bytes
sys.modules.setdefault("cachetools", types.ModuleType("cachetools"))

from unittest.mock import patch

from hummingbot.connector.exchange.backpack_exchange import backpack_constants as CONSTANTS
from hummingbot.connector.exchange.backpack_exchange import backpack_web_utils as web_utils
from hummingbot.connector.exchange.backpack_exchange.backpack_exchange import BackpackExchange


class BackpackExchangeTests(TestCase):
    def setUp(self):
        class DummyConfig:
            rate_limits_share_pct = 1.0

        self.client_config_map = DummyConfig()
        self.exchange = BackpackExchange(
            client_config_map=self.client_config_map,
            backpack_api_key="key",
            backpack_secret_key="secret",
            trading_pairs=["BTC-USDT"],
        )

    def async_run(self, coroutine):
        return asyncio.get_event_loop().run_until_complete(asyncio.wait_for(coroutine, 1))

    def test_initialize_trading_pair_symbols(self):
        exchange_info = {"markets": [{"id": "BTC_USDT", "baseAsset": "BTC", "quoteAsset": "USDT"}]}
        self.exchange._initialize_trading_pair_symbols_from_exchange_info(exchange_info)
        symbol = self.async_run(self.exchange.exchange_symbol_associated_to_pair("BTC-USDT"))
        self.assertEqual("BTC_USDT", symbol)

    def test_get_last_traded_price(self):
        class FakeBidict(dict):
            @property
            def inverse(self):
                return {v: k for k, v in self.items()}

        self.exchange._set_trading_pair_symbol_map(FakeBidict({"BTC_USDT": "BTC-USDT"}))
        with patch.object(self.exchange, "_api_get", new=AsyncMock(return_value={"data": [{"p": "100"}]})):
            price = self.async_run(self.exchange._get_last_traded_price("BTC-USDT"))
        self.assertEqual(100.0, price)

    def test_fetch_trades(self):
        class FakeBidict(dict):
            @property
            def inverse(self):
                return {v: k for k, v in self.items()}

        self.exchange._set_trading_pair_symbol_map(FakeBidict({"BTC_USDT": "BTC-USDT"}))
        response = {
            "data": [
                {"p": "101", "q": "1", "ts": 1700000000000, "side": "buy"},
                {"p": "102", "q": "2", "ts": 1700000001000, "side": "sell"},
            ]
        }
        with patch.object(self.exchange, "_api_get", new=AsyncMock(return_value=response)):
            trades = self.async_run(self.exchange.fetch_trades("BTC-USDT", limit=2))
        self.assertEqual(2, len(trades))
        self.assertEqual(101.0, trades[0]["price"])
        self.assertEqual("sell", trades[1]["side"])

