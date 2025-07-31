import asyncio
import json
import unittest
from decimal import Decimal
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from aioresponses import aioresponses

from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.connector.utils import get_new_client_order_id
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState
from hummingbot.core.data_type.trade_fee import TokenAmount, TradeFeeBase
from hummingbot.core.event.event_logger import EventLogger
from hummingbot.core.event.events import (
    BuyOrderCompletedEvent,
    BuyOrderCreatedEvent,
    MarketEvent,
    OrderCancelledEvent,
    OrderFilledEvent,
)


class TestBackpackExchange(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ev_loop = asyncio.get_event_loop()
        cls.base_asset = "SOL"
        cls.quote_asset = "USDC"
        cls.trading_pair = f"{cls.base_asset}-{cls.quote_asset}"
        cls.exchange_trading_pair = f"{cls.base_asset}_{cls.quote_asset}"

    def setUp(self):
        """Set up test fixtures"""
        self.log_records = []
        self.client_config_map = ClientConfigAdapter(ClientConfigMap())
        
        self.exchange = BackpackExchange(
            client_config_map=self.client_config_map,
            api_key="test_api_key",
            api_secret="dGVzdF9wcml2YXRlX2tleV8zMl9ieXRlc19sb25nISE=",  # base64 encoded test key
            trading_pairs=[self.trading_pair],
            trading_required=True
        )
        
        self.exchange.logger().setLevel(1)
        self.exchange.logger().addHandler(self)
        
        # Event loggers
        self.buy_order_created_logger = EventLogger()
        self.buy_order_completed_logger = EventLogger()
        self.order_cancelled_logger = EventLogger()
        self.order_filled_logger = EventLogger()
        
        self.exchange.add_listener(MarketEvent.BuyOrderCreated, self.buy_order_created_logger)
        self.exchange.add_listener(MarketEvent.BuyOrderCompleted, self.buy_order_completed_logger)
        self.exchange.add_listener(MarketEvent.OrderCancelled, self.order_cancelled_logger)
        self.exchange.add_listener(MarketEvent.OrderFilled, self.order_filled_logger)

    def tearDown(self):
        self.ev_loop.run_until_complete(self.exchange._clean_async_task())

    def handle(self, record):
        self.log_records.append(record)

    def async_run_with_timeout(self, coroutine):
        return self.ev_loop.run_until_complete(asyncio.wait_for(coroutine, 30))

    def get_exchange_rules_mock(self) -> Dict[str, Any]:
        """Mock response for trading rules"""
        return [
            {
                "symbol": self.exchange_trading_pair,
                "baseCurrency": self.base_asset,
                "quoteCurrency": self.quote_asset,
                "minOrderSize": "0.01",
                "tickSize": "0.01",
                "stepSize": "0.001",
                "minPrice": "0.01",
                "maxPrice": "1000000",
                "minNotional": "10",
                "maxLeverage": "10",
                "baseFee": 100,
                "quoteFee": 100,
                "isSpotAllowed": True,
                "status": "ACTIVE"
            }
        ]

    def get_order_create_response_mock(self, order_id: str) -> Dict[str, Any]:
        """Mock response for order creation"""
        return {
            "id": "123456789",
            "clientOrderId": order_id,
            "symbol": self.exchange_trading_pair,
            "side": "Bid",
            "orderType": "Limit",
            "price": "100.0",
            "quantity": "1.0",
            "status": "NEW",
            "executedQuantity": "0",
            "executedQuoteQuantity": "0",
            "timeInForce": "GTC",
            "timestamp": 1614550000000
        }

    def test_supported_order_types(self):
        """Test supported order types"""
        supported_types = self.exchange.supported_order_types()
        self.assertIn(OrderType.LIMIT, supported_types)
        self.assertIn(OrderType.MARKET, supported_types)
        self.assertEqual(len(supported_types), 2)

    @aioresponses()
    def test_update_trading_rules(self, mock_api):
        """Test updating trading rules from the exchange"""
        url = f"{CONSTANTS.REST_URL}/{CONSTANTS.MARKETS_PATH_URL}"
        mock_api.get(url, body=json.dumps(self.get_exchange_rules_mock()))
        
        self.async_run_with_timeout(self.exchange._update_trading_rules())
        
        trading_rule = self.exchange._trading_rules[self.trading_pair]
        self.assertIsInstance(trading_rule, TradingRule)
        self.assertEqual(trading_rule.trading_pair, self.trading_pair)
        self.assertEqual(trading_rule.min_order_size, Decimal("0.01"))
        self.assertEqual(trading_rule.min_price_increment, Decimal("0.01"))
        self.assertEqual(trading_rule.min_base_amount_increment, Decimal("0.001"))
        self.assertEqual(trading_rule.min_notional_size, Decimal("10"))

    def test_create_order_without_trading_rules(self):
        """Test that order creation fails without trading rules"""
        order_id = get_new_client_order_id(is_buy=True, trading_pair=self.trading_pair)
        
        with self.assertRaises(ValueError) as context:
            self.async_run_with_timeout(
                self.exchange._create_order(
                    trade_type=TradeType.BUY,
                    order_id=order_id,
                    trading_pair=self.trading_pair,
                    amount=Decimal("1"),
                    order_type=OrderType.LIMIT,
                    price=Decimal("100")
                )
            )
        
        self.assertIn("trading rules", str(context.exception).lower())

    @aioresponses()
    def test_create_buy_limit_order(self, mock_api):
        """Test creating a buy limit order"""
        # First set up trading rules
        rules_url = f"{CONSTANTS.REST_URL}/{CONSTANTS.MARKETS_PATH_URL}"
        mock_api.get(rules_url, body=json.dumps(self.get_exchange_rules_mock()))
        self.async_run_with_timeout(self.exchange._update_trading_rules())
        
        # Mock order creation
        order_url = f"{CONSTANTS.REST_URL}/{CONSTANTS.ORDER_CREATE_PATH_URL}"
        order_id = get_new_client_order_id(is_buy=True, trading_pair=self.trading_pair)
        mock_api.post(order_url, body=json.dumps(self.get_order_create_response_mock(order_id)))
        
        # Create order
        self.async_run_with_timeout(
            self.exchange._create_order(
                trade_type=TradeType.BUY,
                order_id=order_id,
                trading_pair=self.trading_pair,
                amount=Decimal("1"),
                order_type=OrderType.LIMIT,
                price=Decimal("100")
            )
        )
        
        # Check that order was tracked
        self.assertIn(order_id, self.exchange.in_flight_orders)
        order = self.exchange.in_flight_orders[order_id]
        self.assertEqual(order.client_order_id, order_id)
        self.assertEqual(order.trading_pair, self.trading_pair)
        self.assertEqual(order.trade_type, TradeType.BUY)
        self.assertEqual(order.order_type, OrderType.LIMIT)
        self.assertEqual(order.price, Decimal("100"))
        self.assertEqual(order.amount, Decimal("1"))
        
        # Check event was logged
        self.assertEqual(len(self.buy_order_created_logger.event_log), 1)
        event: BuyOrderCreatedEvent = self.buy_order_created_logger.event_log[0]
        self.assertEqual(event.order_id, order_id)
        self.assertEqual(event.amount, Decimal("1"))
        self.assertEqual(event.price, Decimal("100"))

    @aioresponses()
    def test_cancel_order(self, mock_api):
        """Test cancelling an order"""
        # Set up trading rules
        rules_url = f"{CONSTANTS.REST_URL}/{CONSTANTS.MARKETS_PATH_URL}"
        mock_api.get(rules_url, body=json.dumps(self.get_exchange_rules_mock()))
        self.async_run_with_timeout(self.exchange._update_trading_rules())
        
        # Create an in-flight order
        order_id = get_new_client_order_id(is_buy=True, trading_pair=self.trading_pair)
        exchange_order_id = "123456789"
        self.exchange._order_tracker.start_tracking_order(
            InFlightOrder(
                client_order_id=order_id,
                exchange_order_id=exchange_order_id,
                trading_pair=self.trading_pair,
                trade_type=TradeType.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("100"),
                amount=Decimal("1"),
                creation_timestamp=1614550000
            )
        )
        
        # Mock cancel response
        cancel_url = f"{CONSTANTS.REST_URL}/{CONSTANTS.ORDER_DELETE_PATH_URL}"
        mock_api.delete(cancel_url, body=json.dumps({"status": "success"}))
        
        # Cancel order
        cancellation_result = self.async_run_with_timeout(
            self.exchange._execute_cancel(self.trading_pair, order_id)
        )
        
        self.assertEqual(cancellation_result, order_id)

    def test_demo_mode(self):
        """Test that demo mode is enabled when no API credentials"""
        demo_exchange = BackpackExchange(
            client_config_map=self.client_config_map,
            api_key="",
            api_secret="",
            trading_pairs=[self.trading_pair]
        )
        
        self.assertTrue(demo_exchange._demo_mode)
        self.assertFalse(demo_exchange._trading_required)

    @aioresponses()
    def test_get_last_traded_prices(self, mock_api):
        """Test fetching last traded prices"""
        url = f"{CONSTANTS.REST_URL}/{CONSTANTS.TICKER_PATH_URL}"
        mock_response = {
            "symbol": self.exchange_trading_pair,
            "lastPrice": "150.50",
            "volume": "1000",
            "high": "155.00",
            "low": "145.00"
        }
        mock_api.get(url, body=json.dumps(mock_response))
        
        result = self.async_run_with_timeout(
            self.exchange._get_last_traded_prices([self.trading_pair])
        )
        
        self.assertEqual(result[self.trading_pair], 150.50)

    def test_trading_pair_conversion(self):
        """Test conversion between exchange and hummingbot trading pair formats"""
        from hummingbot.connector.exchange.backpack import backpack_utils as utils
        
        # Test conversion to exchange format
        exchange_pair = utils.convert_to_exchange_trading_pair(self.trading_pair)
        self.assertEqual(exchange_pair, self.exchange_trading_pair)
        
        # Test conversion from exchange format
        hb_pair = utils.convert_from_exchange_trading_pair(self.exchange_trading_pair)
        self.assertEqual(hb_pair, self.trading_pair)

    def test_get_fee(self):
        """Test fee calculation"""
        # Test maker fee
        maker_fee = self.exchange.get_fee(
            self.base_asset,
            self.quote_asset,
            OrderType.LIMIT,
            TradeType.BUY,
            Decimal("1"),
            Decimal("100"),
            is_maker=True
        )
        self.assertIsInstance(maker_fee, TradeFeeBase)
        
        # Test taker fee
        taker_fee = self.exchange.get_fee(
            self.base_asset,
            self.quote_asset,
            OrderType.MARKET,
            TradeType.BUY,
            Decimal("1"),
            Decimal("100"),
            is_maker=False
        )
        self.assertIsInstance(taker_fee, TradeFeeBase)

    def test_is_order_not_found_during_cancelation_error(self):
        """Test order not found error detection during cancellation"""
        # Test with INVALID_ORDER error
        error = Exception("INVALID_ORDER: Order does not exist")
        self.assertTrue(self.exchange._is_order_not_found_during_cancelation_error(error))
        
        # Test with RESOURCE_NOT_FOUND error
        error = Exception("RESOURCE_NOT_FOUND: The order was not found")
        self.assertTrue(self.exchange._is_order_not_found_during_cancelation_error(error))
        
        # Test with unknown error
        error = Exception("UNKNOWN_ERROR: Something went wrong")
        self.assertFalse(self.exchange._is_order_not_found_during_cancelation_error(error))

    def test_is_order_not_found_during_status_update_error(self):
        """Test order not found error detection during status update"""
        # Test with RESOURCE_NOT_FOUND error
        error = Exception("RESOURCE_NOT_FOUND: Order not found")
        self.assertTrue(self.exchange._is_order_not_found_during_status_update_error(error))
        
        # Test with ORDER DOES NOT EXIST error
        error = Exception("ORDER DOES NOT EXIST")
        self.assertTrue(self.exchange._is_order_not_found_during_status_update_error(error))
        
        # Test with different error
        error = Exception("INSUFFICIENT_BALANCE")
        self.assertFalse(self.exchange._is_order_not_found_during_status_update_error(error))

    @patch("hummingbot.connector.exchange.backpack.backpack_exchange.BackpackExchange._time_synchronizer")
    def test_place_order_demo_mode(self, mock_time_sync):
        """Test order placement in demo mode"""
        mock_time_sync.time.return_value = 1614550000.0
        
        # Create demo exchange
        demo_exchange = BackpackExchange(
            client_config_map=self.client_config_map,
            api_key="",
            api_secret="",
            trading_pairs=[self.trading_pair],
            demo_mode=True
        )
        
        order_id = get_new_client_order_id(is_buy=True, trading_pair=self.trading_pair)
        
        # Place order in demo mode
        result = self.async_run_with_timeout(
            demo_exchange._place_order(
                order_id=order_id,
                trading_pair=self.trading_pair,
                amount=Decimal("1"),
                trade_type=TradeType.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("100")
            )
        )
        
        # Should return tuple of (exchange_order_id, timestamp)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertTrue(result[0].startswith("DEMO-"))
        self.assertEqual(result[1], 1614550000.0)

    def test_get_order_book_data(self):
        """Test that order book data source is created correctly"""
        data_source = self.exchange._create_order_book_data_source()
        self.assertIsNotNone(data_source)
        self.assertEqual(data_source._trading_pairs, [self.trading_pair])

    def test_user_stream_data_source_with_credentials(self):
        """Test user stream data source creation with API credentials"""
        data_source = self.exchange._create_user_stream_data_source()
        self.assertIsNotNone(data_source)
        self.assertIsNotNone(data_source._auth)

    def test_user_stream_data_source_without_credentials(self):
        """Test user stream data source creation without API credentials"""
        exchange_no_auth = BackpackExchange(
            client_config_map=self.client_config_map,
            api_key="",
            api_secret="",
            trading_pairs=[self.trading_pair]
        )
        
        data_source = exchange_no_auth._create_user_stream_data_source()
        self.assertIsNone(data_source)


if __name__ == "__main__":
    unittest.main()