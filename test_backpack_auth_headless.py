#!/usr/bin/env python
"""
Test script to verify Backpack Exchange authentication in headless mode.
This script tests the authentication flow using encrypted API keys from the config file.
"""
import asyncio
import sys
import os
import logging
import time
from decimal import Decimal

# Add hummingbot root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.security import Security
from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
from hummingbot.core.event.events import OrderFilledEvent, BuyOrderCreatedEvent, SellOrderCreatedEvent
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.clock import Clock, ClockMode

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_authentication():
    """Test Backpack Exchange authentication and basic operations"""
    logger = logging.getLogger("test_backpack_auth")
    
    try:
        # Initialize security with password
        logger.info("Initializing security with password...")
        from hummingbot.client.config.config_crypt import ETHKeyFileSecretManger
        
        # Create secrets manager with password
        secrets_manager = ETHKeyFileSecretManger("j17crypto")
        Security.login(secrets_manager)
        
        # Get decrypted API keys
        logger.info("Retrieving API keys from encrypted config...")
        api_keys = Security.api_keys("backpack")
        
        if not api_keys:
            logger.error("No API keys found for backpack connector")
            return
        
        # Map keys correctly
        api_key = api_keys.get("backpack_api_key", "")
        api_secret = api_keys.get("backpack_api_secret", "")
        
        logger.info(f"API Key present: {bool(api_key)}")
        logger.info(f"API Secret present: {bool(api_secret)}")
        
        # Create client config
        client_config = ClientConfigAdapter(ClientConfigMap())
        
        # Initialize the exchange connector
        logger.info("Creating Backpack Exchange connector...")
        exchange = BackpackExchange(
            client_config_map=client_config,
            api_key=api_key,
            api_secret=api_secret,
            trading_pairs=["SOL-USDC"],
            trading_required=True,
            demo_mode=False  # Explicitly disable demo mode
        )
        
        # Create clock and add exchange to it
        logger.info("Creating clock...")
        clock = Clock(ClockMode.REALTIME, tick_size=1.0)
        clock.add_iterator(exchange)
        
        # Start the exchange
        logger.info("Starting exchange network...")
        await exchange.start_network()
        
        # Use clock context to run for a short time
        async def wait_for_ready():
            logger.info("Waiting for exchange to be ready...")
            max_wait = 30  # seconds
            start_time = time.time()
            
            with clock:
                # Run the clock for max_wait seconds or until ready
                wait_task = asyncio.create_task(clock.run_til(time.time() + max_wait))
                
                while not exchange.ready and (time.time() - start_time) < max_wait:
                    await asyncio.sleep(1)
                    elapsed = int(time.time() - start_time)
                    if elapsed % 5 == 0:
                        logger.info(f"Still waiting... ({elapsed}s)")
                
                # Cancel the clock task
                wait_task.cancel()
                try:
                    await wait_task
                except asyncio.CancelledError:
                    pass
            
            return exchange.ready
        
        ready = await wait_for_ready()
        
        if not ready:
            logger.error(f"Exchange not ready after {max_wait} seconds")
            # Log some debug info
            logger.info(f"Trading pair symbol map ready: {exchange.trading_pair_symbol_map_ready()}")
            logger.info(f"Trading rules: {len(exchange._trading_rules)}")
            return
        
        logger.info("Exchange is ready!")
        
        # Test 1: Fetch balances
        logger.info("\n=== Testing Balance Fetching ===")
        await exchange._update_balances()
        
        all_balances = exchange.get_all_balances()
        logger.info(f"Balances retrieved: {len(all_balances)} assets")
        for asset, balance in all_balances.items():
            logger.info(f"  {asset}: {balance}")
        
        # Test 2: Get order book
        logger.info("\n=== Testing Order Book ===")
        order_book = exchange.get_order_book("SOL-USDC")
        if order_book:
            bid_price = order_book.get_price(False)
            ask_price = order_book.get_price(True)
            logger.info(f"Order book for SOL-USDC:")
            logger.info(f"  Best bid: {bid_price}")
            logger.info(f"  Best ask: {ask_price}")
            logger.info(f"  Spread: {ask_price - bid_price if bid_price and ask_price else 'N/A'}")
        else:
            logger.warning("Order book not available")
        
        # Test 3: Check trading rules
        logger.info("\n=== Testing Trading Rules ===")
        trading_rule = exchange.trading_rules.get("SOL-USDC")
        if trading_rule:
            logger.info(f"Trading rule for SOL-USDC:")
            logger.info(f"  Min order size: {trading_rule.min_order_size}")
            logger.info(f"  Max order size: {trading_rule.max_order_size}")
            logger.info(f"  Min price increment: {trading_rule.min_price_increment}")
            logger.info(f"  Min base amount increment: {trading_rule.min_base_amount_increment}")
        else:
            logger.warning("Trading rule not found for SOL-USDC")
        
        # Test 4: Place a test order (very small, below market)
        logger.info("\n=== Testing Order Placement ===")
        if bid_price and all_balances.get("USDC", 0) > 0:
            # Place a buy order 20% below current bid
            test_price = bid_price * Decimal("0.8")
            test_amount = Decimal("0.01")  # Very small amount
            
            logger.info(f"Placing test buy order: {test_amount} SOL @ {test_price} USDC")
            
            # Set up event listener
            order_created = False
            def on_order_created(event):
                nonlocal order_created
                order_created = True
                logger.info(f"Order created event received: {event.order_id}")
            
            exchange.add_listener(BuyOrderCreatedEvent, on_order_created)
            
            try:
                order_id = exchange.buy(
                    trading_pair="SOL-USDC",
                    amount=test_amount,
                    order_type=OrderType.LIMIT,
                    price=test_price
                )
                logger.info(f"Order placement initiated with ID: {order_id}")
                
                # Wait a bit for the order to be processed
                await asyncio.sleep(5)
                
                # Check active orders
                active_orders = exchange.active_orders
                logger.info(f"Active orders: {len(active_orders)}")
                for order in active_orders:
                    logger.info(f"  Order {order.client_order_id}: {order.amount} @ {order.price}")
                
                # Cancel the test order
                if active_orders:
                    logger.info("Cancelling test order...")
                    exchange.cancel(
                        trading_pair="SOL-USDC",
                        client_order_id=order_id
                    )
                    await asyncio.sleep(3)
                    logger.info("Order cancelled")
                
            except Exception as e:
                logger.error(f"Error placing/cancelling order: {e}", exc_info=True)
        else:
            logger.warning("Skipping order test - no USDC balance or price data")
        
        logger.info("\n=== Authentication Test Complete ===")
        
    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
    finally:
        # Clean up
        if 'exchange' in locals():
            await exchange.stop_network()
            logger.info("Exchange stopped")


if __name__ == "__main__":
    asyncio.run(test_authentication())