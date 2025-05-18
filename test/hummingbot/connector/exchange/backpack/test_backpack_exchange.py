import asyncio
import sys
import types
from decimal import Decimal
from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import OrderState

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


class BackpackExchangeTests(TestCase):
    def setUp(self):
        self.client_config_map = ClientConfigAdapter(ClientConfigMap())
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
        self.assertEqual(Decimal("100"), price)

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
        self.assertEqual(Decimal("101"), trades[0]["price"])
        self.assertEqual("sell", trades[1]["side"])

    @patch.object(BackpackExchange, "_api_post", new_callable=AsyncMock)
    @patch.object(BackpackExchange, "exchange_symbol_associated_to_pair", new_callable=AsyncMock)
    def test_place_order(self, mock_pair, mock_post):
        mock_pair.return_value = "BTC_USDT"
        mock_post.return_value = {"order_id": "123", "ts": 1700000000000}
        order_id, ts = self.async_run(
            self.exchange._place_order(
                "OID1",
                "BTC-USDT",
                Decimal("1"),
                TradeType.BUY,
                OrderType.LIMIT,
                Decimal("100"),
            )
        )
        self.assertEqual("123", order_id)
        self.assertEqual(Decimal("1700000000"), ts)

    @patch.object(BackpackExchange, "_api_delete", new_callable=AsyncMock)
    def test_place_cancel(self, mock_delete):
        order = MagicMock()
        order.get_exchange_order_id = AsyncMock(return_value="111")
        mock_delete.return_value = {"status": "success"}
        result = self.async_run(self.exchange._place_cancel("OID1", order))
        self.assertTrue(result)

    @patch.object(BackpackExchange, "_api_get", new_callable=AsyncMock)
    def test_request_order_status(self, mock_get):
        order = MagicMock(client_order_id="OID1", trading_pair="BTC-USDT")
        order.get_exchange_order_id = AsyncMock(return_value="111")
        mock_get.return_value = {"status": "filled"}
        order_update = self.async_run(self.exchange._request_order_status(order))
        self.assertEqual(OrderState.FILLED, order_update.new_state)

    @patch.object(BackpackExchange, "_api_get", new_callable=AsyncMock)
    def test_update_balances(self, mock_get):
        mock_get.return_value = {"data": [{"asset": "BTC", "available": "1", "total": "2"}]}
        self.async_run(self.exchange._update_balances())
        self.assertEqual(Decimal("1"), self.exchange.available_balances["BTC"])
        self.assertEqual(Decimal("2"), self.exchange.get_balance("BTC"))

    @patch.object(BackpackExchange, "_api_get", new_callable=AsyncMock)
    @patch.object(BackpackExchange, "trading_pair_associated_to_exchange_symbol")
    def test_update_trading_rules(self, mock_trading_pair_associated, mock_get):
        # Mock the trading pair association response
        mock_trading_pair_associated.return_value = "BTC-USDT"

        mock_get.return_value = {
            "markets": [
                {
                    "id": "BTC_USDT",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "minOrderSize": "0.001",
                    "tickSize": "0.01",
                    "stepSize": "0.0001",
                    "minNotional": "5",
                }
            ]
        }

        self.async_run(self.exchange._update_trading_rules())

        rule = self.exchange._trading_rules.get("BTC-USDT")
        self.assertIsNotNone(rule)
        self.assertEqual(Decimal("0.001"), rule.min_order_size)
        self.assertEqual(Decimal("0.01"), rule.min_price_increment)
        self.assertEqual(Decimal("0.0001"), rule.min_base_amount_increment)
        self.assertEqual(Decimal("5"), rule.min_notional_size)

    def test_order_book_tracker_uses_custom_order_book(self):
        order_book = self.exchange._orderbook_ds.order_book_create_function()
        from hummingbot.connector.exchange.backpack.backpack_order_book import BackpackOrderBook

        self.assertIsInstance(order_book, BackpackOrderBook)
