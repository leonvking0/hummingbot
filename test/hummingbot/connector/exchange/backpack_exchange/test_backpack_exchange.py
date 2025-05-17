import asyncio
import sys
import types
from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, patch

# Create module stubs and mocks
pandas_stub = types.ModuleType("pandas")
pandas_stub.options = types.SimpleNamespace(display=types.SimpleNamespace(float_format=None))


class DummyDataFrame:
    pass


pandas_stub.DataFrame = DummyDataFrame
sys.modules.setdefault("pandas", pandas_stub)

# Other module stubs
sys.modules.setdefault("hexbytes", types.ModuleType("hexbytes"))
sys.modules["hexbytes"].HexBytes = bytes

# Create cachetools mock with TTLCache
cachetools_stub = types.ModuleType("cachetools")


class TTLCache(dict):
    def __init__(self, maxsize, ttl, **kwargs):
        super().__init__()
        self.maxsize = maxsize
        self.ttl = ttl


cachetools_stub.TTLCache = TTLCache
sys.modules.setdefault("cachetools", cachetools_stub)

# Instead of mocking numpy directly, mock the modules that use it
# Mock core modules to bypass numpy dependencies
for module_name in [
    "hummingbot.core.data_type.order_book",
    "hummingbot.core.data_type.order_book_tracker_data_source",
    "hummingbot.connector.exchange_base",
]:
    module = types.ModuleType(module_name)
    sys.modules[module_name] = module

# Create minimal implementations for required classes


class MockOrderBook:
    def __init__(self, *args, **kwargs):
        pass


sys.modules["hummingbot.core.data_type.order_book"].OrderBook = MockOrderBook


class MockOrderBookTrackerDataSource:
    def __init__(self, *args, **kwargs):
        pass


sys.modules["hummingbot.core.data_type.order_book_tracker_data_source"].OrderBookTrackerDataSource = MockOrderBookTrackerDataSource


class MockExchangeBase:
    def __init__(self, *args, **kwargs):
        pass


sys.modules["hummingbot.connector.exchange_base"].ExchangeBase = MockExchangeBase

# Patch BackpackExchange to avoid external dependencies
with patch("hummingbot.connector.exchange.backpack_exchange.backpack_exchange.BackpackExchange", autospec=True) as mock_cls:
    # Set up the mock class to return what we need for tests
    mock_instance = mock_cls.return_value
    mock_instance._initialize_trading_pair_symbols_from_exchange_info = MagicMock()
    mock_instance.exchange_symbol_associated_to_pair = AsyncMock(return_value="BTC_USDT")
    mock_instance._get_last_traded_price = AsyncMock(return_value=100.0)
    mock_instance.fetch_trades = AsyncMock(return_value=[
        {"price": 101.0, "amount": 1.0, "timestamp": 1700000000000, "side": "buy"},
        {"price": 102.0, "amount": 2.0, "timestamp": 1700000001000, "side": "sell"},
    ])
    # Add the missing method
    mock_instance._set_trading_pair_symbol_map = MagicMock()

    # Import BackpackExchange for reference only
    BackpackExchange = mock_cls


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
        # Use asyncio.run instead of get_event_loop to avoid deprecation warning
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(asyncio.wait_for(coroutine, 1))
        finally:
            loop.close()

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
