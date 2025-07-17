import asyncio
import json
import time
import unittest
from decimal import Decimal
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

from aioresponses import aioresponses

from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState


class TestBackpackExchange(unittest.TestCase):
    """Test cases for Backpack Exchange connector"""
    
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.ev_loop = asyncio.get_event_loop()
        cls.base_asset = "SOL"
        cls.quote_asset = "USDC"
        cls.trading_pair = f"{cls.base_asset}-{cls.quote_asset}"
        cls.exchange_trading_pair = f"{cls.base_asset}_{cls.quote_asset}"
    
    def setUp(self) -> None:
        super().setUp()
        
        # Create client config
        self.client_config_map = ClientConfigAdapter(ClientConfigMap())
        
        # Create exchange instance without API keys (public data only)
        self.exchange = BackpackExchange(
            client_config_map=self.client_config_map,
            api_key="",
            api_secret="",
            trading_pairs=[self.trading_pair],
            trading_required=False,
        )
        
        # Mock web assistants factory
        self.rest_assistant = AsyncMock()
        web_assistants_factory = AsyncMock()
        web_assistants_factory.get_rest_assistant.return_value = self.rest_assistant
        self.exchange._web_assistants_factory = web_assistants_factory
        self.exchange._throttler = MagicMock()
    
    def async_run_with_timeout(self, coroutine, timeout: float = 1):
        return self.ev_loop.run_until_complete(asyncio.wait_for(coroutine, timeout))
    
    def test_update_trading_rules(self):
        """Test updating trading rules from exchange"""
        mock_response = [
            {
                "symbol": self.exchange_trading_pair,
                "status": "ONLINE",
                "filters": {
                    "price": {
                        "tickSize": "0.01",
                    },
                    "quantity": {
                        "minQuantity": "0.1",
                        "maxQuantity": "10000",
                        "stepSize": "0.1",
                    },
                },
            }
        ]
        
        self.rest_assistant.execute_request.return_value = mock_response
        
        self.async_run_with_timeout(self.exchange._update_trading_rules())
        
        trading_rule = self.exchange.trading_rules.get(self.trading_pair)
        self.assertIsNotNone(trading_rule)
        self.assertEqual(trading_rule.min_order_size, Decimal("0.1"))
        self.assertEqual(trading_rule.max_order_size, Decimal("10000"))
        self.assertEqual(trading_rule.min_price_increment, Decimal("0.01"))
        self.assertEqual(trading_rule.min_base_amount_increment, Decimal("0.1"))
    
    @patch("hummingbot.connector.exchange.backpack.backpack_exchange.BackpackExchange._api_post")
    async def test_place_order(self, mock_api_post):
        """Test placing an order"""
        self.exchange._trading_required = True
        self.exchange._auth = MagicMock()
        
        # Mock API response
        mock_api_post.return_value = {
            "id": "123456789",
            "symbol": self.exchange_trading_pair,
            "side": "Bid",
            "orderType": "Limit",
            "price": "20.5",
            "quantity": "1",
            "status": "New",
        }
        
        # Place order
        order_id = "test-order-123"
        amount = Decimal("1")
        price = Decimal("20.5")
        
        exchange_order_id = await self.exchange._place_order(
            order_id=order_id,
            trading_pair=self.trading_pair,
            amount=amount,
            trade_type=TradeType.BUY,
            order_type=OrderType.LIMIT,
            price=price,
        )
        
        self.assertEqual(exchange_order_id, "123456789")
        
        # Verify API call
        mock_api_post.assert_called_once()
        call_args = mock_api_post.call_args[1]
        self.assertEqual(call_args["path_url"], CONSTANTS.ORDER_PATH_URL)
        self.assertTrue(call_args["is_auth_required"])
        
        # Verify order data
        order_data = call_args["data"]
        self.assertEqual(order_data["symbol"], self.exchange_trading_pair)
        self.assertEqual(order_data["side"], "Bid")
        self.assertEqual(order_data["orderType"], "Limit")
        self.assertEqual(order_data["quantity"], "1")
        self.assertEqual(order_data["price"], "20.5")
        self.assertEqual(order_data["timeInForce"], "GTC")
    
    @patch("hummingbot.connector.exchange.backpack.backpack_exchange.BackpackExchange._api_delete")
    async def test_cancel_order(self, mock_api_delete):
        """Test cancelling an order"""
        self.exchange._trading_required = True
        self.exchange._auth = MagicMock()
        
        # Create tracked order
        tracked_order = InFlightOrder(
            client_order_id="test-order-123",
            exchange_order_id="123456789",
            trading_pair=self.trading_pair,
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            price=Decimal("20.5"),
            amount=Decimal("1"),
            creation_timestamp=time.time(),
        )
        
        # Mock API response
        mock_api_delete.return_value = {
            "id": "123456789",
            "status": "Cancelled",
        }
        
        # Cancel order
        await self.exchange._place_cancel("test-order-123", tracked_order)
        
        # Verify API call
        mock_api_delete.assert_called_once()
        call_args = mock_api_delete.call_args[1]
        self.assertEqual(call_args["path_url"], CONSTANTS.ORDER_PATH_URL)
        self.assertTrue(call_args["is_auth_required"])
        
        # Verify cancel data
        cancel_data = call_args["data"]
        self.assertEqual(cancel_data["symbol"], self.exchange_trading_pair)
        self.assertEqual(cancel_data["orderId"], "123456789")
    
    @patch("hummingbot.connector.exchange.backpack.backpack_exchange.BackpackExchange._api_get")
    async def test_update_balances(self, mock_api_get):
        """Test updating account balances"""
        self.exchange._trading_required = True
        self.exchange._auth = MagicMock()
        
        # Mock API response
        mock_api_get.return_value = [
            {
                "symbol": "SOL",
                "available": "10.5",
                "locked": "0.5",
            },
            {
                "symbol": "USDC",
                "available": "1000",
                "locked": "50",
            },
        ]
        
        # Update balances
        await self.exchange._update_balances()
        
        # Verify API call
        mock_api_get.assert_called_once_with(
            path_url=CONSTANTS.BALANCES_PATH_URL,
            is_auth_required=True
        )
        
        # Check balances
        self.assertEqual(self.exchange.available_balances["SOL"], Decimal("10.5"))
        self.assertEqual(self.exchange.available_balances["USDC"], Decimal("1000"))
        self.assertEqual(self.exchange.get_balance("SOL"), Decimal("11"))  # 10.5 + 0.5
        self.assertEqual(self.exchange.get_balance("USDC"), Decimal("1050"))  # 1000 + 50
    
    def test_get_last_traded_price(self):
        """Test getting last traded price"""
        mock_response = {
            "symbol": self.exchange_trading_pair,
            "lastPrice": "20.5",
        }
        
        self.rest_assistant.execute_request.return_value = mock_response
        
        price = self.async_run_with_timeout(
            self.exchange._get_last_traded_price(self.trading_pair)
        )
        
        self.assertEqual(price, 20.5)
    
    def test_supported_order_types(self):
        """Test supported order types"""
        supported_types = self.exchange.supported_order_types()
        self.assertIn(OrderType.LIMIT, supported_types)
        self.assertIn(OrderType.MARKET, supported_types)
    
    def test_is_cancel_request_in_exchange_synchronous(self):
        """Test if cancel requests are synchronous"""
        self.assertFalse(self.exchange.is_cancel_request_in_exchange_synchronous)
    
    def test_trading_pair_conversion(self):
        """Test trading pair format conversion"""
        from hummingbot.connector.exchange.backpack import backpack_utils as utils
        
        # Test conversion to exchange format
        exchange_pair = utils.convert_to_exchange_trading_pair(self.trading_pair)
        self.assertEqual(exchange_pair, self.exchange_trading_pair)
        
        # Test conversion from exchange format
        hb_pair = utils.convert_from_exchange_trading_pair(self.exchange_trading_pair)
        self.assertEqual(hb_pair, self.trading_pair)
    
    def test_order_not_found_errors(self):
        """Test order not found error detection"""
        # Test cancellation error
        error = Exception("INVALID_ORDER: Order not found")
        self.assertTrue(self.exchange._is_order_not_found_during_cancelation_error(error))
        
        error = Exception("Some other error")
        self.assertFalse(self.exchange._is_order_not_found_during_cancelation_error(error))
        
        # Test status update error
        error = Exception("RESOURCE_NOT_FOUND: Order does not exist")
        self.assertTrue(self.exchange._is_order_not_found_during_status_update_error(error))
        
        error = Exception("Some other error")
        self.assertFalse(self.exchange._is_order_not_found_during_status_update_error(error))


if __name__ == "__main__":
    unittest.main()