#!/usr/bin/env python3
"""
Simplified test script for Backpack Exchange trading functions
Focuses on core functionality without event listeners
"""

import asyncio
import logging
import os
import sys
from decimal import Decimal
from typing import Optional
from pathlib import Path

# Try to load from .env file if dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # If dotenv not available, try to load .env manually
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value

# Add hummingbot to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
from hummingbot.core.data_type.common import OrderType, TradeType

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('backpack_test_simple.log')
    ]
)

logger = logging.getLogger(__name__)


class BackpackSimpleTest:
    """Simplified test harness for Backpack Exchange"""
    
    def __init__(self, api_key: str, api_secret: str, trading_pair: str = "SOL-USDC"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.trading_pair = trading_pair
        self.exchange: Optional[BackpackExchange] = None
        
        # Test parameters
        self.test_amount = Decimal("0.001")  # Small test amount
        self.price_offset = Decimal("0.2")   # 20% offset from mid price for safety
        
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
            
            # Start the exchange
            await self.exchange.start_network()
            
            logger.info("Exchange initialized successfully")
            
            # Wait for connections to establish
            await asyncio.sleep(3)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize exchange: {e}", exc_info=True)
            return False
    
    async def test_authentication(self):
        """Test authentication and balance retrieval"""
        logger.info("\n=== Testing Authentication ===")
        try:
            # Update balances
            logger.info("Fetching account balances...")
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
            
            # Also get trading rules
            logger.info("\nFetching trading rules...")
            await self.exchange._update_trading_rules()
            
            trading_rule = self.exchange.trading_rules.get(self.trading_pair)
            if trading_rule:
                logger.info(f"Trading rule for {self.trading_pair}:")
                logger.info(f"  Min order size: {trading_rule.min_order_size}")
                logger.info(f"  Max order size: {trading_rule.max_order_size}")
                logger.info(f"  Min price increment: {trading_rule.min_price_increment}")
                logger.info(f"  Min base amount increment: {trading_rule.min_base_amount_increment}")
            
            return True
            
        except Exception as e:
            logger.error(f"Authentication test failed: {e}", exc_info=True)
            return False
    
    async def get_mid_price(self) -> Optional[Decimal]:
        """Get the current mid price for the trading pair"""
        try:
            # Wait for order book to be available
            logger.info("Waiting for order book data...")
            max_retries = 10
            retry_count = 0
            
            while retry_count < max_retries:
                order_book = self.exchange.get_order_book(self.trading_pair)
                if order_book and len(order_book.bid_entries()) > 0 and len(order_book.ask_entries()) > 0:
                    break
                await asyncio.sleep(1)
                retry_count += 1
            
            if not order_book:
                logger.error("Order book not available after waiting")
                return None
            
            bid_price = order_book.get_price(False)  # Best bid
            ask_price = order_book.get_price(True)   # Best ask
            
            if bid_price and ask_price:
                mid_price = (bid_price + ask_price) / 2
                logger.info(f"Best bid: {bid_price}, Best ask: {ask_price}, Mid price: {mid_price}")
                return Decimal(str(mid_price))
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get mid price: {e}", exc_info=True)
            return None
    
    async def test_order_placement(self):
        """Test placing a limit order"""
        logger.info("\n=== Testing Order Placement ===")
        try:
            # Get current market price
            mid_price = await self.get_mid_price()
            if not mid_price:
                logger.error("Could not get mid price")
                return None
            
            # Calculate test order price (20% below mid for buy)
            buy_price = mid_price * (Decimal("1") - self.price_offset)
            
            # Ensure price follows trading rules
            trading_rule = self.exchange.trading_rules.get(self.trading_pair)
            if trading_rule:
                buy_price = self.exchange.quantize_order_price(self.trading_pair, buy_price)
                test_amount = self.exchange.quantize_order_amount(self.trading_pair, self.test_amount)
            else:
                test_amount = self.test_amount
            
            logger.info(f"Placing buy order: {test_amount} @ {buy_price} {self.trading_pair}")
            
            # Get a unique client order ID
            from hummingbot.connector.utils import get_new_client_order_id
            client_order_id = get_new_client_order_id(
                is_buy=True,
                trading_pair=self.trading_pair,
                hbot_order_id_prefix="TEST"
            )
            
            logger.info(f"Client order ID: {client_order_id}")
            
            # Place the order directly using the internal method
            exchange_order_id = await self.exchange._place_order(
                order_id=client_order_id,
                trading_pair=self.trading_pair,
                amount=test_amount,
                trade_type=TradeType.BUY,
                order_type=OrderType.LIMIT,
                price=buy_price
            )
            
            logger.info(f"Order placed successfully. Exchange order ID: {exchange_order_id}")
            
            # Track the order
            self.exchange.start_tracking_order(
                order_id=client_order_id,
                exchange_order_id=exchange_order_id,
                trading_pair=self.trading_pair,
                trade_type=TradeType.BUY,
                price=buy_price,
                amount=test_amount,
                order_type=OrderType.LIMIT
            )
            
            return client_order_id, exchange_order_id
            
        except Exception as e:
            logger.error(f"Order placement test failed: {e}", exc_info=True)
            return None, None
    
    async def test_order_status(self, client_order_id: str, exchange_order_id: str):
        """Check order status"""
        logger.info("\n=== Testing Order Status ===")
        try:
            # Wait a bit for order to be processed
            await asyncio.sleep(2)
            
            # Check in-flight orders
            in_flight_order = self.exchange.in_flight_orders.get(client_order_id)
            if in_flight_order:
                logger.info(f"Order found in flight:")
                logger.info(f"  Client ID: {in_flight_order.client_order_id}")
                logger.info(f"  Exchange ID: {in_flight_order.exchange_order_id}")
                logger.info(f"  Status: {in_flight_order.current_state}")
                logger.info(f"  Amount: {in_flight_order.amount}")
                logger.info(f"  Price: {in_flight_order.price}")
            else:
                logger.warning("Order not found in in-flight orders")
            
            # Try to update order status
            logger.info("\nUpdating order status from exchange...")
            await self.exchange._update_order_status()
            
            return True
            
        except Exception as e:
            logger.error(f"Order status check failed: {e}", exc_info=True)
            return False
    
    async def test_order_cancellation(self, client_order_id: str):
        """Test cancelling an order"""
        logger.info("\n=== Testing Order Cancellation ===")
        try:
            in_flight_order = self.exchange.in_flight_orders.get(client_order_id)
            if not in_flight_order:
                logger.error(f"Order {client_order_id} not found in in-flight orders")
                return False
            
            logger.info(f"Attempting to cancel order: {client_order_id}")
            
            # Cancel the order using internal method
            await self.exchange._place_cancel(client_order_id, in_flight_order)
            
            logger.info("Cancel request sent")
            
            # Wait for cancellation to process
            await asyncio.sleep(2)
            
            # Update order status
            await self.exchange._update_order_status()
            
            # Check if order was cancelled
            if client_order_id not in self.exchange.in_flight_orders:
                logger.info("Order successfully removed from in-flight orders")
            else:
                order = self.exchange.in_flight_orders.get(client_order_id)
                logger.info(f"Order still in flight with status: {order.current_state if order else 'Unknown'}")
            
            return True
            
        except Exception as e:
            logger.error(f"Order cancellation test failed: {e}", exc_info=True)
            return False
    
    async def run_all_tests(self):
        """Run all tests in sequence"""
        logger.info("Starting Backpack Exchange trading tests...")
        logger.info(f"Trading pair: {self.trading_pair}")
        logger.info(f"Test amount: {self.test_amount}")
        
        # Initialize exchange
        if not await self.initialize():
            logger.error("Failed to initialize exchange")
            return
        
        try:
            # Test authentication
            if not await self.test_authentication():
                logger.error("Authentication test failed")
                return
            
            # Test order placement
            client_order_id, exchange_order_id = await self.test_order_placement()
            if not client_order_id:
                logger.error("Order placement test failed")
                return
            
            # Check order status
            await self.test_order_status(client_order_id, exchange_order_id)
            
            # Wait before cancelling
            logger.info("\nWaiting 3 seconds before cancellation...")
            await asyncio.sleep(3)
            
            # Test order cancellation
            await self.test_order_cancellation(client_order_id)
            
        finally:
            # Clean up
            logger.info("\nTests completed. Shutting down...")
            await self.exchange.stop_network()


async def main():
    """Main entry point"""
    # Check for API credentials
    api_key = os.getenv("BACKPACK_API_KEY")
    api_secret = os.getenv("BACKPACK_API_SECRET")
    
    if not api_key or not api_secret:
        logger.error("Please set BACKPACK_API_KEY and BACKPACK_API_SECRET")
        logger.error("These should be in your .env file")
        return
    
    # Create and run test
    tester = BackpackSimpleTest(api_key, api_secret)
    await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())