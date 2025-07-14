import asyncio
import unittest
from decimal import Decimal
from typing import Awaitable
from unittest.mock import AsyncMock, MagicMock, patch

from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.connector.derivative.backpack_perpetual.backpack_perpetual_derivative import BackpackPerpetualDerivative
from hummingbot.connector.derivative.backpack_perpetual import backpack_perpetual_constants as CONSTANTS
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, PositionMode, TradeType
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.event.event_logger import EventLogger
from hummingbot.core.event.events import MarketEvent


class BackpackPerpetualDerivativeTest(unittest.TestCase):
    # Set the duration for which the async function will be tested
    ev_loop_run_time = 0.01

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ev_loop = asyncio.get_event_loop()
        cls.base_asset = "BTC"
        cls.quote_asset = "USDC"
        cls.trading_pair = f"{cls.base_asset}-{cls.quote_asset}-PERP"
        cls.exchange_trading_pair = f"{cls.base_asset}_{cls.quote_asset}_PERP"

    def setUp(self):
        super().setUp()
        self.log_records = []
        
        # Create client config
        self.client_config_map = ClientConfigAdapter(ClientConfigMap())
        
        # Create the exchange connector
        self.exchange = BackpackPerpetualDerivative(
            client_config_map=self.client_config_map,
            api_key="test_api_key",
            api_secret="test_api_secret",
            trading_pairs=[self.trading_pair],
            trading_required=False,
        )
        
        # Set up event loggers
        self.buy_order_created_logger = EventLogger()
        self.sell_order_created_logger = EventLogger()
        self.order_cancelled_logger = EventLogger()
        self.order_filled_logger = EventLogger()
        
        # Connect event loggers
        self.exchange.add_listener(MarketEvent.BuyOrderCreated, self.buy_order_created_logger)
        self.exchange.add_listener(MarketEvent.SellOrderCreated, self.sell_order_created_logger)
        self.exchange.add_listener(MarketEvent.OrderCancelled, self.order_cancelled_logger)
        self.exchange.add_listener(MarketEvent.OrderFilled, self.order_filled_logger)

    def tearDown(self):
        super().tearDown()

    def async_run_with_timeout(self, coroutine: Awaitable, timeout: float = 1):
        ret = self.ev_loop.run_until_complete(asyncio.wait_for(coroutine, timeout))
        return ret

    def _simulate_trading_rules_initialized(self):
        """Helper method to simulate trading rules being initialized"""
        trading_rule = TradingRule(
            trading_pair=self.trading_pair,
            min_order_size=Decimal("0.001"),
            max_order_size=Decimal("10000"),
            min_price_increment=Decimal("0.01"),
            min_base_amount_increment=Decimal("0.001"),
            min_quote_amount_increment=Decimal("0.01"),
            min_notional_size=Decimal("10"),
            min_order_value=Decimal("0"),
            supports_limit_orders=True,
            supports_market_orders=True,
        )
        self.exchange._trading_rules[self.trading_pair] = trading_rule

    def test_connector_name(self):
        self.assertEqual(self.exchange.name, CONSTANTS.EXCHANGE_NAME)

    def test_supported_order_types(self):
        supported_types = self.exchange.supported_order_types()
        self.assertIn(OrderType.LIMIT, supported_types)
        self.assertIn(OrderType.MARKET, supported_types)

    def test_supported_position_modes(self):
        supported_modes = self.exchange.supported_position_modes()
        self.assertIn(PositionMode.ONEWAY, supported_modes)
        self.assertIn(PositionMode.HEDGE, supported_modes)

    def test_get_buy_and_sell_collateral_tokens(self):
        buy_token = self.exchange.get_buy_collateral_token(self.trading_pair)
        sell_token = self.exchange.get_sell_collateral_token(self.trading_pair)
        
        # For perpetuals, both should be the quote currency
        self.assertEqual(buy_token, self.quote_asset)
        self.assertEqual(sell_token, self.quote_asset)

    def test_trading_pair_conversion(self):
        from hummingbot.connector.derivative.backpack_perpetual import backpack_perpetual_utils as utils
        
        # Test conversion from exchange to hummingbot format
        hb_pair = utils.convert_from_exchange_trading_pair(self.exchange_trading_pair)
        self.assertEqual(hb_pair, self.trading_pair)
        
        # Test conversion from hummingbot to exchange format
        exchange_pair = utils.convert_to_exchange_trading_pair(self.trading_pair)
        self.assertEqual(exchange_pair, self.exchange_trading_pair)

    def test_split_trading_pair(self):
        from hummingbot.connector.derivative.backpack_perpetual import backpack_perpetual_utils as utils
        
        base, quote = utils.split_trading_pair(self.trading_pair)
        self.assertEqual(base, self.base_asset)
        self.assertEqual(quote, self.quote_asset)

    @patch("hummingbot.connector.derivative.backpack_perpetual.backpack_perpetual_derivative.BackpackPerpetualDerivative._api_get")
    def test_update_trading_rules(self, mock_api_get):
        # Mock market data response
        mock_markets = [
            {
                "symbol": "BTC_USDC_PERP",
                "status": "ONLINE",
                "marketType": "PERP",
                "filters": {
                    "price": {
                        "tickSize": "0.01"
                    },
                    "quantity": {
                        "minQuantity": "0.001",
                        "maxQuantity": "10000",
                        "stepSize": "0.001"
                    },
                    "notional": {
                        "minNotional": "10"
                    }
                },
                "contractMultiplier": "1",
                "maxLeverage": "20"
            },
            {
                "symbol": "ETH_USDC_PERP",
                "status": "ONLINE",
                "marketType": "PERP",
                "filters": {
                    "price": {
                        "tickSize": "0.01"
                    },
                    "quantity": {
                        "minQuantity": "0.01",
                        "maxQuantity": "50000",
                        "stepSize": "0.01"
                    }
                }
            },
            {
                "symbol": "SOL_USDC",
                "status": "ONLINE",
                "marketType": "SPOT",  # Should be filtered out
                "filters": {}
            }
        ]
        
        mock_api_get.return_value = mock_markets
        
        # Run the update
        self.async_run_with_timeout(self.exchange._update_trading_rules())
        
        # Check that trading rules were created for perpetual markets only
        self.assertIn("BTC-USDC-PERP", self.exchange._trading_rules)
        self.assertIn("ETH-USDC-PERP", self.exchange._trading_rules)
        self.assertNotIn("SOL-USDC", self.exchange._trading_rules)
        
        # Check specific rule values
        btc_rule = self.exchange._trading_rules["BTC-USDC-PERP"]
        self.assertEqual(btc_rule.min_order_size, Decimal("0.001"))
        self.assertEqual(btc_rule.max_order_size, Decimal("10000"))
        self.assertEqual(btc_rule.min_price_increment, Decimal("0.01"))
        self.assertEqual(btc_rule.min_notional_size, Decimal("10"))

    def test_parse_trading_rule(self):
        from hummingbot.connector.derivative.backpack_perpetual import backpack_perpetual_utils as utils
        
        market_info = {
            "filters": {
                "price": {
                    "tickSize": "0.01"
                },
                "quantity": {
                    "minQuantity": "0.001",
                    "maxQuantity": "10000",
                    "stepSize": "0.001"
                },
                "notional": {
                    "minNotional": "10"
                }
            },
            "contractMultiplier": "1",
            "maxLeverage": "20"
        }
        
        parsed_rule = utils.parse_trading_rule(market_info)
        
        self.assertEqual(parsed_rule["min_order_size"], Decimal("0.001"))
        self.assertEqual(parsed_rule["max_order_size"], Decimal("10000"))
        self.assertEqual(parsed_rule["min_price_increment"], Decimal("0.01"))
        self.assertEqual(parsed_rule["min_base_amount_increment"], Decimal("0.001"))
        self.assertEqual(parsed_rule["min_notional_size"], Decimal("10"))
        self.assertEqual(parsed_rule["max_leverage"], Decimal("20"))
        self.assertEqual(parsed_rule["contract_multiplier"], Decimal("1"))

    def test_is_order_not_found_errors(self):
        # Test during status update
        error_msg = "INVALID_ORDER: Order not found"
        exception = Exception(error_msg)
        self.assertTrue(self.exchange._is_order_not_found_during_status_update_error(exception))
        
        error_msg = "RESOURCE_NOT_FOUND: The requested order does not exist"
        exception = Exception(error_msg)
        self.assertTrue(self.exchange._is_order_not_found_during_status_update_error(exception))
        
        # Test during cancellation
        error_msg = "INVALID_ORDER: Cannot cancel order"
        exception = Exception(error_msg)
        self.assertTrue(self.exchange._is_order_not_found_during_cancelation_error(exception))
        
        # Test non-matching error
        error_msg = "INSUFFICIENT_BALANCE: Not enough funds"
        exception = Exception(error_msg)
        self.assertFalse(self.exchange._is_order_not_found_during_status_update_error(exception))

    def test_create_order_book_data_source(self):
        data_source = self.exchange._create_order_book_data_source()
        self.assertEqual(data_source._trading_pairs, [self.trading_pair])
        self.assertEqual(data_source._domain, self.exchange._domain)

    @patch("hummingbot.connector.derivative.backpack_perpetual.backpack_perpetual_api_order_book_data_source.BackpackPerpetualAPIOrderBookDataSource.get_new_order_book")
    def test_order_book_creation(self, mock_get_new_order_book):
        # Create a mock order book
        mock_order_book = OrderBook()
        mock_get_new_order_book.return_value = mock_order_book
        
        # Initialize order book tracker
        self.exchange._initialize_order_book_tracker()
        
        # Start the exchange
        self.async_run_with_timeout(self.exchange._update_trading_rules())
        self._simulate_trading_rules_initialized()
        
        # Verify order book data source was created
        self.assertIsNotNone(self.exchange._order_book_tracker._data_source)

    def test_funding_fee_poll_interval(self):
        # Should be half of the funding interval (4 hours)
        expected_interval = CONSTANTS.FUNDING_RATE_INTERVAL_HOURS * 3600 // 2
        self.assertEqual(self.exchange.funding_fee_poll_interval, expected_interval)

    def test_get_new_client_order_id(self):
        from hummingbot.connector.derivative.backpack_perpetual import backpack_perpetual_utils as utils
        
        # Test client order ID generation
        buy_order_id = utils.get_new_perp_client_order_id(
            is_buy=True,
            trading_pair=self.trading_pair,
            current_timestamp=1234567890.123
        )
        
        # Should be a numeric string
        self.assertTrue(buy_order_id.isdigit())
        
        # Should fit in uint32 range
        self.assertLess(int(buy_order_id), 2**32)

    def test_parse_funding_info(self):
        from hummingbot.connector.derivative.backpack_perpetual import backpack_perpetual_utils as utils
        
        funding_data = {
            "fundingRate": "0.0001",
            "nextFundingTime": 1234567890000,  # milliseconds
            "fundingInterval": 28800  # 8 hours in seconds
        }
        
        parsed = utils.parse_funding_info(funding_data)
        
        self.assertEqual(parsed["funding_rate"], Decimal("0.0001"))
        self.assertEqual(parsed["next_funding_timestamp"], 1234567890)  # converted to seconds
        self.assertEqual(parsed["funding_interval"], 28800)

    def test_parse_position_info(self):
        from hummingbot.connector.derivative.backpack_perpetual import backpack_perpetual_utils as utils
        
        # Test long position
        position_data = {
            "q": "1.5",  # positive quantity = long
            "P": "100",  # unrealized PnL
            "B": "50000",  # entry price
            "l": "45000",  # liquidation price
            "M": "51000",  # mark price
            "leverage": "10"
        }
        
        parsed = utils.parse_position_info(position_data, self.trading_pair)
        
        self.assertEqual(parsed["trading_pair"], self.trading_pair)
        self.assertEqual(parsed["position_side"], "LONG")
        self.assertEqual(parsed["amount"], Decimal("1.5"))
        self.assertEqual(parsed["unrealized_pnl"], Decimal("100"))
        self.assertEqual(parsed["entry_price"], Decimal("50000"))
        self.assertEqual(parsed["liquidation_price"], Decimal("45000"))
        self.assertEqual(parsed["mark_price"], Decimal("51000"))
        self.assertEqual(parsed["leverage"], Decimal("10"))
        
        # Test short position
        position_data["q"] = "-1.5"  # negative quantity = short
        parsed = utils.parse_position_info(position_data, self.trading_pair)
        
        self.assertEqual(parsed["position_side"], "SHORT")
        self.assertEqual(parsed["amount"], Decimal("1.5"))  # should be positive

    def test_not_implemented_methods(self):
        # Test that methods requiring private API raise NotImplementedError
        with self.assertRaises(NotImplementedError):
            self.async_run_with_timeout(
                self.exchange._place_order(
                    order_id="test_order",
                    trading_pair=self.trading_pair,
                    amount=Decimal("1"),
                    trade_type=TradeType.BUY,
                    order_type=OrderType.LIMIT,
                    price=Decimal("50000")
                )
            )
        
        with self.assertRaises(NotImplementedError):
            self.async_run_with_timeout(
                self.exchange._place_cancel("test_order", None)
            )


if __name__ == "__main__":
    unittest.main()