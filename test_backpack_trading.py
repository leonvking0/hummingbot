#!/usr/bin/env python3
"""
Standalone test script for Backpack Exchange trading functions
Tests basic operations: authentication, order placement, and cancellation
"""

import asyncio
import logging
import os
import sys
from decimal import Decimal
from typing import Optional

# Add hummingbot to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.event.events import (
    BuyOrderCreatedEvent,
    MarketOrderFailureEvent,
    OrderCancelledEvent,
    OrderFilledEvent,
    SellOrderCreatedEvent,
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('backpack_test.log')
    ]
)

logger = logging.getLogger(__name__)


class BackpackTradingTest:
    """Test harness for Backpack Exchange trading functions"""
    
    def __init__(self, api_key: str, api_secret: str, trading_pair: str = "SOL-USDC"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.trading_pair = trading_pair
        self.exchange: Optional[BackpackExchange] = None
        
        # Test parameters
        self.test_amount = Decimal("0.001")  # Small test amount
        self.price_offset = Decimal("0.1")   # 10% offset from mid price
        
    async def initialize(self):
        """Initialize the exchange connector"""
        try:
            logger.info("Initializing Backpack Exchange connector...")
            
            # Create client config
            client_config = ClientConfigAdapter(ClientConfigMap())
            
            # Create exchange instance
            self.exchange = BackpackExchange(
                client_config_map=client_config,
                api_key=self.api_key,
                api_secret=self.api_secret,
                trading_pairs=[self.trading_pair],
                trading_required=True,
            )
            
            # Set up event listeners
            self.exchange.add_listener(BuyOrderCreatedEvent, self.on_buy_order_created)
            self.exchange.add_listener(SellOrderCreatedEvent, self.on_sell_order_created)
            self.exchange.add_listener(OrderFilledEvent, self.on_order_filled)
            self.exchange.add_listener(OrderCancelledEvent, self.on_order_cancelled)
            self.exchange.add_listener(MarketOrderFailureEvent, self.on_order_failure)
            
            # Start the exchange
            await self.exchange.start_network()
            
            logger.info("Exchange initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize exchange: {e}", exc_info=True)
            return False
    
    async def test_authentication(self):
        """Test authentication and balance retrieval"""
        logger.info("\n=== Testing Authentication ===")
        try:
            # Update balances
            await self.exchange._update_balances()
            
            # Get balances
            balances = self.exchange.available_balances
            logger.info(f"Available balances: {dict(balances)}")
            
            # Check if we have the required assets
            base, quote = self.trading_pair.split("-")
            base_balance = balances.get(base, Decimal("0"))
            quote_balance = balances.get(quote, Decimal("0"))
            
            logger.info(f"{base} balance: {base_balance}")
            logger.info(f"{quote} balance: {quote_balance}")
            
            return True
            
        except Exception as e:
            logger.error(f"Authentication test failed: {e}", exc_info=True)
            return False
    
    async def test_order_placement(self):
        """Test placing a limit order"""
        logger.info("\n=== Testing Order Placement ===")
        try:
            # Get current market price
            mid_price = await self.get_mid_price()
            if not mid_price:
                logger.error("Could not get mid price")
                return False
            
            # Calculate test order price (10% below mid for buy)
            buy_price = mid_price * (Decimal("1") - self.price_offset)
            buy_price = self.exchange.quantize_order_price(self.trading_pair, buy_price)
            
            logger.info(f"Mid price: {mid_price}")
            logger.info(f"Test buy price: {buy_price}")
            logger.info(f"Test amount: {self.test_amount}")
            
            # Place buy order
            logger.info("Placing buy order...")
            order_id = await self.exchange.place_order(
                trading_pair=self.trading_pair,
                amount=self.test_amount,
                is_buy=True,
                order_type=OrderType.LIMIT,
                price=buy_price
            )
            
            logger.info(f"Order placed successfully. Client order ID: {order_id}")
            
            # Wait a bit for order to be processed
            await asyncio.sleep(2)
            
            # Check order status
            in_flight_orders = list(self.exchange.in_flight_orders.values())
            logger.info(f"In-flight orders: {len(in_flight_orders)}")
            
            for order in in_flight_orders:
                logger.info(f"Order: {order.client_order_id}, Status: {order.current_state}, "
                          f"Exchange ID: {order.exchange_order_id}")
            
            return order_id
            
        except Exception as e:
            logger.error(f"Order placement test failed: {e}", exc_info=True)
            return None
    
    async def test_order_cancellation(self, order_id: str):
        """Test cancelling an order"""
        logger.info("\n=== Testing Order Cancellation ===")
        try:
            logger.info(f"Attempting to cancel order: {order_id}")
            
            # Cancel the order
            await self.exchange.cancel(
                trading_pair=self.trading_pair,
                client_order_id=order_id
            )
            
            logger.info("Cancel request sent")
            
            # Wait for cancellation to process
            await asyncio.sleep(2)
            
            # Check if order was cancelled
            in_flight_orders = list(self.exchange.in_flight_orders.values())
            logger.info(f"Remaining in-flight orders: {len(in_flight_orders)}")
            
            return True
            
        except Exception as e:
            logger.error(f"Order cancellation test failed: {e}", exc_info=True)
            return False
    
    async def get_mid_price(self) -> Optional[Decimal]:
        """Get the current mid price for the trading pair"""
        try:
            # Ensure order book is available
            await asyncio.sleep(1)  # Give time for order book to populate
            
            order_book = self.exchange.get_order_book(self.trading_pair)
            if not order_book:
                logger.error("Order book not available")
                return None
            
            bid_price = order_book.get_price(False)  # Best bid
            ask_price = order_book.get_price(True)   # Best ask
            
            if bid_price and ask_price:
                mid_price = (bid_price + ask_price) / 2
                return Decimal(str(mid_price))
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get mid price: {e}", exc_info=True)
            return None
    
    # Event handlers
    def on_buy_order_created(self, event: BuyOrderCreatedEvent):
        logger.info(f"Buy order created: {event.order_id}")
    
    def on_sell_order_created(self, event: SellOrderCreatedEvent):
        logger.info(f"Sell order created: {event.order_id}")
    
    def on_order_filled(self, event: OrderFilledEvent):
        logger.info(f"Order filled: {event.order_id}, Amount: {event.amount}, Price: {event.price}")
    
    def on_order_cancelled(self, event: OrderCancelledEvent):
        logger.info(f"Order cancelled: {event.order_id}")
    
    def on_order_failure(self, event: MarketOrderFailureEvent):
        logger.error(f"Order failed: {event.order_id}, Error: {event.error_message}")
    
    async def run_all_tests(self):
        """Run all tests in sequence"""
        logger.info("Starting Backpack Exchange trading tests...")
        
        # Initialize exchange
        if not await self.initialize():
            logger.error("Failed to initialize exchange")
            return
        
        # Wait for exchange to be ready
        logger.info("Waiting for exchange to be ready...")
        await asyncio.sleep(5)
        
        # Test authentication
        if not await self.test_authentication():
            logger.error("Authentication test failed")
            return
        
        # Test order placement
        order_id = await self.test_order_placement()
        if not order_id:
            logger.error("Order placement test failed")
            return
        
        # Wait before cancelling
        await asyncio.sleep(3)
        
        # Test order cancellation
        if not await self.test_order_cancellation(order_id):
            logger.error("Order cancellation test failed")
        
        # Clean up
        logger.info("\nTests completed. Shutting down...")
        await self.exchange.stop_network()


async def main():
    """Main entry point"""
    # Check for API credentials
    api_key = os.getenv("BACKPACK_API_KEY")
    api_secret = os.getenv("BACKPACK_API_SECRET")
    
    if not api_key or not api_secret:
        logger.error("Please set BACKPACK_API_KEY and BACKPACK_API_SECRET environment variables")
        logger.error("Example:")
        logger.error("export BACKPACK_API_KEY='your_base64_public_key'")
        logger.error("export BACKPACK_API_SECRET='your_base64_private_key'")
        return
    
    # Create and run test
    tester = BackpackTradingTest(api_key, api_secret)
    await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())