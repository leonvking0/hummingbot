#!/usr/bin/env python3
import asyncio
import logging
import os
import sys
from decimal import Decimal
from typing import Dict, Optional

# Add hummingbot to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
from hummingbot.core.clock import Clock, ClockMode
from hummingbot.core.data_type.common import OrderType, PriceType, TradeType
from hummingbot.core.data_type.limit_order import LimitOrder
from hummingbot.core.event.event_forwarder import SourceInfoEventForwarder
from hummingbot.core.event.events import (
    BuyOrderCompletedEvent,
    MarketEvent,
    OrderFilledEvent,
    SellOrderCompletedEvent,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SimpleBackpackBuyBot:
    def __init__(
        self,
        trading_pair: str = "SOL-USDC",
        order_amount: Decimal = Decimal("0.1"),
        price_discount: Decimal = Decimal("0.1"),
        order_refresh_time: int = 60,
        api_key: str = "",  # Not used - public API only
        api_secret: str = ""  # Not used - public API only
    ):
        self.trading_pair = trading_pair
        self.order_amount = order_amount
        self.price_discount = price_discount
        self.order_refresh_time = order_refresh_time
        self.api_key = api_key
        self.api_secret = api_secret
        
        self.connector: Optional[BackpackExchange] = None
        self.clock: Optional[Clock] = None
        self.last_order_timestamp = 0
        self._is_running = False
        self._main_task = None
        
        # Event listeners
        self.buy_order_completed_listener = None
        self.sell_order_completed_listener = None
        self.order_filled_listener = None
        
    async def start(self):
        """Initialize and start the bot"""
        try:
            # Initialize client config
            client_config = ClientConfigAdapter(ClientConfigMap())
            
            # Initialize the connector
            logger.info("Initializing Backpack connector...")
            self.connector = BackpackExchange(
                client_config_map=client_config,
                api_key="",  # Public API only for now
                api_secret="",  # Public API only for now
                trading_pairs=[self.trading_pair],
                trading_required=False  # Public API only implementation
            )
            
            # Update trading rules
            if hasattr(self.connector, '_update_trading_rules'):
                await self.connector._update_trading_rules()
            
            # Start the network connection
            logger.info("Starting network connection...")
            await self.connector.start_network()
            
            # Initialize the clock
            self.clock = Clock(ClockMode.REALTIME, tick_size=1.0)
            self.clock.add_iterator(self.connector)
            
            # Set up event listeners
            self.setup_event_listeners()
            
            # Wait for the connector to be ready
            while not self.connector.ready:
                logger.info("Waiting for connector to be ready...")
                await asyncio.sleep(1)
            
            logger.info("Connector is ready. Starting trading loop...")
            self._is_running = True
            
            # Start the main trading loop
            self._main_task = asyncio.create_task(self.run_trading_loop())
            await self._main_task
            
        except Exception as e:
            import traceback
            logger.error(f"Error starting bot: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    def setup_event_listeners(self):
        """Set up event listeners for order events"""
        if self.connector:
            # Listen for buy order completed events
            self.buy_order_completed_listener = SourceInfoEventForwarder(
                self._on_buy_order_completed
            )
            self.connector.add_listener(
                MarketEvent.BuyOrderCompleted,
                self.buy_order_completed_listener
            )
            
            # Listen for order filled events
            self.order_filled_listener = SourceInfoEventForwarder(
                self._on_order_filled
            )
            self.connector.add_listener(
                MarketEvent.OrderFilled,
                self.order_filled_listener
            )
    
    def _on_buy_order_completed(self, event_tag: int, market: BackpackExchange, event: BuyOrderCompletedEvent):
        """Handle buy order completed event"""
        logger.info(
            f"Buy order completed: {event.base_asset_amount} {event.base_asset} "
            f"@ {event.quote_asset_amount / event.base_asset_amount:.4f} {event.quote_asset}"
        )
    
    def _on_order_filled(self, event_tag: int, market: BackpackExchange, event: OrderFilledEvent):
        """Handle order filled event"""
        logger.info(
            f"Order filled: {event.trade_type.name} {event.amount} {event.trading_pair} "
            f"@ {event.price:.4f}"
        )
    
    async def stop(self):
        """Stop the bot and clean up resources"""
        self._is_running = False
        
        # Cancel the main task
        if self._main_task and not self._main_task.done():
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass
        
        # Cancel all active orders
        if self.connector:
            await self.cancel_all_orders()
            
            # Remove event listeners
            if self.buy_order_completed_listener:
                self.connector.remove_listener(
                    MarketEvent.BuyOrderCompleted,
                    self.buy_order_completed_listener
                )
            if self.order_filled_listener:
                self.connector.remove_listener(
                    MarketEvent.OrderFilled,
                    self.order_filled_listener
                )
            
            # Stop the connector
            await self.connector.stop_network()
            
        logger.info("Bot stopped successfully")
    
    async def run_trading_loop(self):
        """Main trading loop"""
        tick_count = 0
        
        while self._is_running:
            try:
                # Process one clock tick
                self.clock.tick(tick_count)
                
                # Check if it's time to refresh orders
                current_time = self.clock.current_timestamp
                if current_time - self.last_order_timestamp >= self.order_refresh_time:
                    await self.refresh_orders()
                    self.last_order_timestamp = current_time
                
                # Sleep for the tick size
                await asyncio.sleep(1.0)
                tick_count += 1
                
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                # Continue running unless it's a critical error
                if "Network" in str(e):
                    logger.error("Network error detected, stopping bot...")
                    break
    
    async def refresh_orders(self):
        """Cancel existing orders and place new ones"""
        try:
            # Cancel all existing orders
            await self.cancel_all_orders()
            
            # Get current mid price
            mid_price = self.connector.get_price_by_type(
                self.trading_pair,
                PriceType.MidPrice
            )
            
            if mid_price is None or mid_price <= 0:
                logger.warning(f"Unable to get valid mid price for {self.trading_pair}")
                return
            
            # Calculate buy price with discount
            buy_price = mid_price * (Decimal("1") - self.price_discount)
            
            # Get the quantized values according to trading rules
            trading_rule = self.connector.trading_rules.get(self.trading_pair)
            if trading_rule:
                buy_price = self.connector.quantize_order_price(self.trading_pair, buy_price)
                order_amount = self.connector.quantize_order_amount(self.trading_pair, self.order_amount)
            else:
                order_amount = self.order_amount
            
            logger.info(
                f"Placing buy order: {order_amount} @ {buy_price:.4f} "
                f"(mid price: {mid_price:.4f}, discount: {self.price_discount * 100}%)"
            )
            
            # Place the order (simulation only for now)
            logger.info(
                f"[SIMULATION] Would place buy order: "
                f"{order_amount} {self.trading_pair} @ {buy_price:.4f}"
            )
            
        except Exception as e:
            logger.error(f"Error refreshing orders: {e}")
    
    async def cancel_all_orders(self):
        """Cancel all active orders"""
        try:
            # Simulation mode only
            logger.debug("[SIMULATION] Would cancel all active orders")
                
        except Exception as e:
            logger.error(f"Error cancelling orders: {e}")


async def main():
    """Main entry point"""
    # Configuration
    TRADING_PAIR = "SOL-USDC"
    ORDER_AMOUNT = Decimal("0.1")
    PRICE_DISCOUNT = Decimal("0.1")  # 10% below mid price
    ORDER_REFRESH_TIME = 60  # seconds
    
    # Load API keys from environment variables
    API_KEY = os.getenv("BACKPACK_API_KEY", "")
    API_SECRET = os.getenv("BACKPACK_API_SECRET", "")
    
    # Note: Backpack connector currently only supports public API
    logger.info(
        "Note: The Backpack connector currently only supports public API endpoints.\n"
        "Running in simulation mode - orders will not be placed on the exchange."
    )
    
    # Create and start the bot
    bot = SimpleBackpackBuyBot(
        trading_pair=TRADING_PAIR,
        order_amount=ORDER_AMOUNT,
        price_discount=PRICE_DISCOUNT,
        order_refresh_time=ORDER_REFRESH_TIME,
        api_key=API_KEY,
        api_secret=API_SECRET
    )
    
    try:
        logger.info("Starting Backpack Simple Buy Bot...")
        logger.info(f"Trading Pair: {TRADING_PAIR}")
        logger.info(f"Order Amount: {ORDER_AMOUNT}")
        logger.info(f"Price Discount: {PRICE_DISCOUNT * 100}%")
        logger.info(f"Order Refresh Time: {ORDER_REFRESH_TIME} seconds")
        logger.info(f"Mode: SIMULATION (Public API only)")
        
        await bot.start()
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, stopping bot...")
    except Exception as e:
        logger.error(f"Bot crashed with error: {e}")
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())