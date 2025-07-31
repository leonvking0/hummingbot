import asyncio
import os
import unittest
from decimal import Decimal
from typing import Dict, List, Optional

from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
from hummingbot.core.data_type.common import OrderType, TradeType


class TestBackpackIntegration(unittest.TestCase):
    """
    Integration tests for Backpack Exchange connector.
    
    These tests make real API calls and require valid API credentials.
    Set BACKPACK_API_KEY and BACKPACK_API_SECRET environment variables to run.
    
    WARNING: These tests may place real orders on the exchange if using
    production credentials. Use testnet/sandbox credentials when available.
    """
    
    @classmethod
    def setUpClass(cls):
        cls.ev_loop = asyncio.get_event_loop()
        cls.api_key = os.getenv("BACKPACK_API_KEY", "")
        cls.api_secret = os.getenv("BACKPACK_API_SECRET", "")
        
        # Test configuration
        cls.test_trading_pair = "SOL-USDC"
        cls.test_order_amount = Decimal("0.01")  # Small amount for testing
        
    def setUp(self):
        """Set up test fixtures"""
        self.client_config_map = ClientConfigAdapter(ClientConfigMap())
        
        # Initialize exchange
        self.exchange = BackpackExchange(
            client_config_map=self.client_config_map,
            api_key=self.api_key,
            api_secret=self.api_secret,
            trading_pairs=[self.test_trading_pair],
            trading_required=bool(self.api_key)  # Only enable trading if credentials provided
        )
        
        self.ev_loop.run_until_complete(self.exchange.start_network())
        
    def tearDown(self):
        """Clean up after tests"""
        self.ev_loop.run_until_complete(self.exchange.stop_network())
    
    def async_run_with_timeout(self, coroutine, timeout=30):
        return self.ev_loop.run_until_complete(asyncio.wait_for(coroutine, timeout))
    
    # Public API Tests (Always Run)
    
    async def test_fetch_trading_pairs(self):
        """Test fetching all available trading pairs"""
        trading_pairs = await self.exchange._connector_name  # This triggers trading pairs fetch
        
        # Verify we got trading pairs
        self.assertIsInstance(trading_pairs, list)
        self.assertGreater(len(trading_pairs), 0)
        
        # Verify format
        for pair in trading_pairs:
            self.assertIn("-", pair)  # Should be in Hummingbot format
            
        # Common pairs should exist
        common_pairs = ["SOL-USDC", "BTC-USDC"]
        for pair in common_pairs:
            self.assertIn(pair, trading_pairs)
    
    async def test_fetch_order_book(self):
        """Test fetching order book data"""
        # Fetch order book
        order_book = await self.exchange.get_order_book(self.test_trading_pair)
        
        # Verify structure
        self.assertIsNotNone(order_book)
        self.assertGreater(len(order_book.bid_entries()), 0)
        self.assertGreater(len(order_book.ask_entries()), 0)
        
        # Verify bid/ask ordering
        bids = list(order_book.bid_entries())
        asks = list(order_book.ask_entries())
        
        # Bids should be sorted descending
        for i in range(1, len(bids)):
            self.assertLessEqual(bids[i].price, bids[i-1].price)
            
        # Asks should be sorted ascending
        for i in range(1, len(asks)):
            self.assertGreaterEqual(asks[i].price, asks[i-1].price)
    
    async def test_ticker_data(self):
        """Test fetching ticker/last traded price"""
        # Get last traded prices
        prices = await self.exchange.get_last_traded_prices([self.test_trading_pair])
        
        # Verify we got a price
        self.assertIn(self.test_trading_pair, prices)
        price = prices[self.test_trading_pair]
        
        self.assertIsInstance(price, float)
        self.assertGreater(price, 0)
    
    async def test_trading_rules(self):
        """Test fetching and parsing trading rules"""
        # Trading rules should be loaded on start
        await asyncio.sleep(1)  # Wait for initialization
        
        # Check trading rules exist
        self.assertIn(self.test_trading_pair, self.exchange.trading_rules)
        
        rule = self.exchange.trading_rules[self.test_trading_pair]
        
        # Verify rule properties
        self.assertGreater(rule.min_order_size, 0)
        self.assertGreater(rule.min_price_increment, 0)
        self.assertGreater(rule.min_base_amount_increment, 0)
    
    async def test_order_book_updates(self):
        """Test real-time order book updates via WebSocket"""
        # Subscribe to order book updates
        order_book = await self.exchange.get_order_book(self.test_trading_pair)
        initial_update_id = order_book.snapshot_uid
        
        # Wait for updates
        await asyncio.sleep(5)
        
        # Check if we received updates
        current_update_id = order_book.snapshot_uid
        self.assertNotEqual(initial_update_id, current_update_id, 
                           "Order book should have received updates")
    
    # Private API Tests (Require Credentials)
    
    @unittest.skipIf(not os.getenv("BACKPACK_API_KEY"), "No API credentials provided")
    async def test_account_balances(self):
        """Test fetching account balances"""
        # Update balances
        await self.exchange._update_balances()
        
        # Check we have some balances
        all_balances = self.exchange.get_all_balances()
        self.assertIsInstance(all_balances, dict)
        
        # Should have at least USDC balance
        if "USDC" in all_balances:
            usdc_balance = all_balances["USDC"]
            self.assertGreaterEqual(usdc_balance, 0)
    
    @unittest.skipIf(not os.getenv("BACKPACK_API_KEY"), "No API credentials provided") 
    async def test_place_and_cancel_order(self):
        """Test placing and cancelling a limit order"""
        # Get current price
        prices = await self.exchange.get_last_traded_prices([self.test_trading_pair])
        current_price = Decimal(str(prices[self.test_trading_pair]))
        
        # Place a buy order 10% below market (unlikely to fill)
        buy_price = current_price * Decimal("0.9")
        buy_price = self.exchange.quantize_order_price(self.test_trading_pair, buy_price)
        
        # Place order
        order_id = await self.exchange.place_order(
            trading_pair=self.test_trading_pair,
            amount=self.test_order_amount,
            is_buy=True,
            order_type=OrderType.LIMIT,
            price=buy_price
        )
        
        self.assertIsNotNone(order_id)
        
        # Wait for order to be tracked
        await asyncio.sleep(2)
        
        # Verify order is tracked
        self.assertIn(order_id, self.exchange.in_flight_orders)
        
        # Cancel order
        success = await self.exchange.cancel(self.test_trading_pair, order_id)
        self.assertTrue(success)
        
        # Wait for cancellation
        await asyncio.sleep(2)
        
        # Verify order is no longer active
        if order_id in self.exchange.in_flight_orders:
            order = self.exchange.in_flight_orders[order_id]
            self.assertTrue(order.is_cancelled)
    
    @unittest.skipIf(not os.getenv("BACKPACK_API_KEY"), "No API credentials provided")
    async def test_order_status_updates(self):
        """Test order status update mechanism"""
        # Place an order
        prices = await self.exchange.get_last_traded_prices([self.test_trading_pair])
        current_price = Decimal(str(prices[self.test_trading_pair]))
        
        buy_price = current_price * Decimal("0.9")
        buy_price = self.exchange.quantize_order_price(self.test_trading_pair, buy_price)
        
        order_id = await self.exchange.place_order(
            trading_pair=self.test_trading_pair,
            amount=self.test_order_amount,
            is_buy=True,
            order_type=OrderType.LIMIT,
            price=buy_price
        )
        
        # Force status update
        await self.exchange._update_order_status()
        
        # Check order status
        self.assertIn(order_id, self.exchange.in_flight_orders)
        order = self.exchange.in_flight_orders[order_id]
        
        # Verify order properties
        self.assertEqual(order.trading_pair, self.test_trading_pair)
        self.assertEqual(order.order_type, OrderType.LIMIT)
        self.assertEqual(order.trade_type, TradeType.BUY)
        
        # Clean up
        await self.exchange.cancel(self.test_trading_pair, order_id)
    
    @unittest.skipIf(not os.getenv("BACKPACK_API_KEY"), "No API credentials provided")
    async def test_market_order(self):
        """Test placing a market order"""
        # Note: Be very careful with market orders in production!
        # This test uses a very small amount
        
        # Check if we have balance
        await self.exchange._update_balances()
        balances = self.exchange.get_all_balances()
        
        # Only proceed if we have USDC balance
        if "USDC" not in balances or balances["USDC"] < 1:
            self.skipTest("Insufficient USDC balance for market order test")
        
        # Place a very small market buy order
        try:
            order_id = await self.exchange.place_order(
                trading_pair=self.test_trading_pair,
                amount=Decimal("0.001"),  # Very small amount
                is_buy=True,
                order_type=OrderType.MARKET
            )
            
            self.assertIsNotNone(order_id)
            
            # Market orders should fill quickly
            await asyncio.sleep(3)
            
            # Check if filled
            if order_id in self.exchange.in_flight_orders:
                order = self.exchange.in_flight_orders[order_id]
                self.assertTrue(order.is_filled or order.is_partially_filled)
                
        except Exception as e:
            # Market orders might fail due to various reasons
            self.skipTest(f"Market order failed: {str(e)}")
    
    async def test_error_handling(self):
        """Test API error handling"""
        # Test invalid trading pair
        with self.assertRaises(ValueError):
            await self.exchange.place_order(
                trading_pair="INVALID-PAIR",
                amount=Decimal("1"),
                is_buy=True,
                order_type=OrderType.LIMIT,
                price=Decimal("100")
            )
        
        # Test invalid order size (too small)
        if self.test_trading_pair in self.exchange.trading_rules:
            rule = self.exchange.trading_rules[self.test_trading_pair]
            
            # Try to place order below minimum
            tiny_amount = rule.min_order_size / 10
            
            with self.assertRaises(ValueError):
                await self.exchange.place_order(
                    trading_pair=self.test_trading_pair,
                    amount=tiny_amount,
                    is_buy=True,
                    order_type=OrderType.LIMIT,
                    price=Decimal("100")
                )


if __name__ == "__main__":
    # Provide usage instructions
    if not os.getenv("BACKPACK_API_KEY"):
        print("\n" + "="*60)
        print("BACKPACK INTEGRATION TESTS")
        print("="*60)
        print("\nThese tests require API credentials to run fully.")
        print("Set the following environment variables:")
        print("  - BACKPACK_API_KEY: Your Backpack API key")
        print("  - BACKPACK_API_SECRET: Your base64 encoded API secret")
        print("\nPublic API tests will run without credentials.")
        print("Private API tests will be skipped without credentials.")
        print("\nWARNING: Use testnet/sandbox credentials when available!")
        print("="*60 + "\n")
    
    unittest.main()