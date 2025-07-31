import logging
import os
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import Field

from hummingbot.client.config.config_data_types import BaseClientModel
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import OrderType, PriceType, TradeType
from hummingbot.core.data_type.order_candidate import OrderCandidate
from hummingbot.core.event.events import OrderFilledEvent
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class BackpackDemoTestConfig(BaseClientModel):
    script_file_name: str = os.path.basename(__file__)
    exchange: str = Field("backpack")
    trading_pair: str = Field("SOL-USDC")
    order_amount: Decimal = Field(Decimal("0.01"))  # Small amount for testing
    price_discount: Decimal = Field(Decimal("0.1"))  # 10% discount from mid price
    order_refresh_time: int = Field(15)  # Check every 15 seconds in demo mode


class BackpackDemoTest(ScriptStrategyBase):
    """
    Demo script to test Backpack exchange connector without API credentials.
    This script:
    1. Uses the connector in demo mode
    2. Places a small buy order below the current mid price
    3. Monitors the order status and logs updates
    4. Demonstrates that the connector can work without actual API keys
    """

    # Define markets as a class attribute
    markets = {"backpack": {"SOL-USDC"}}
    create_timestamp = 0

    @classmethod
    def init_markets(cls, config: BackpackDemoTestConfig):
        cls.markets = {config.exchange: {config.trading_pair}}

    def __init__(self, connectors: Dict[str, ConnectorBase], config: Optional[BackpackDemoTestConfig] = None):
        super().__init__(connectors)
        self.config = config or BackpackDemoTestConfig()
        self.logger().info(f"BackpackDemoTest initialized with config: exchange={self.config.exchange}, "
                          f"trading_pair={self.config.trading_pair}, order_amount={self.config.order_amount}")
        
        # Enable demo mode by setting it on the connector
        connector = self.connectors[self.config.exchange]
        if hasattr(connector, '_demo_mode'):
            connector._demo_mode = True
            self.logger().info("Demo mode enabled on Backpack connector")

    def on_tick(self):
        """
        Called every second. Checks connector status and places orders.
        """
        try:
            # Log connector status periodically
            if self.current_timestamp % 10 == 0:  # Every 10 seconds
                connector = self.connectors[self.config.exchange]
                self.logger().info(f"Connector ready: {connector.ready}")
                self.logger().info(f"Balances: {connector.get_all_balances()}")
                
                # Log order book status
                mid_price = connector.get_price_by_type(
                    self.config.trading_pair, 
                    PriceType.MidPrice
                )
                if mid_price and mid_price > 0:
                    self.logger().info(f"Mid price for {self.config.trading_pair}: {mid_price:.4f}")
            
            # Place orders at intervals
            if self.create_timestamp <= self.current_timestamp:
                # Cancel all existing orders
                self.cancel_all_orders()
                
                # Create and place new order
                proposal = self.create_proposal()
                if proposal:
                    proposal_adjusted = self.adjust_proposal_to_budget(proposal)
                    if proposal_adjusted:
                        self.place_orders(proposal_adjusted)
                        self.logger().info(f"Demo: Placed buy order for {self.config.order_amount} SOL")
                    else:
                        self.logger().warning("Demo: Insufficient balance to place order (this is expected in demo mode)")
                
                # Set next refresh time
                self.create_timestamp = self.config.order_refresh_time + self.current_timestamp
                
        except Exception as e:
            self.logger().error(f"Error in on_tick: {e}", exc_info=True)

    def create_proposal(self) -> List[OrderCandidate]:
        """
        Creates a buy order proposal at 10% below mid price
        """
        try:
            # Get mid price from the exchange
            mid_price = self.connectors[self.config.exchange].get_price_by_type(
                self.config.trading_pair, 
                PriceType.MidPrice
            )
            
            if mid_price is None or mid_price <= 0:
                self.logger().warning(f"Unable to get valid mid price for {self.config.trading_pair}")
                return []
            
            # Calculate buy price with discount
            buy_price = mid_price * (Decimal("1") - self.config.price_discount)
            
            # Create buy order candidate
            buy_order = OrderCandidate(
                trading_pair=self.config.trading_pair,
                is_maker=True,
                order_type=OrderType.LIMIT,
                order_side=TradeType.BUY,
                amount=self.config.order_amount,
                price=buy_price
            )
            
            self.logger().info(f"Created buy order: {self.config.order_amount} SOL @ {buy_price:.4f} USDC "
                             f"(mid price: {mid_price:.4f})")
            
            return [buy_order]
            
        except Exception as e:
            self.logger().error(f"Error creating order proposal: {e}")
            return []

    def adjust_proposal_to_budget(self, proposal: List[OrderCandidate]) -> List[OrderCandidate]:
        """
        Adjusts proposal to available budget
        """
        try:
            # In demo mode, just return the proposal as-is
            return proposal
        except Exception as e:
            self.logger().error(f"Error adjusting proposal to budget: {e}")
            return []

    def place_orders(self, proposal: List[OrderCandidate]) -> None:
        """
        Places the orders from the proposal
        """
        for order in proposal:
            self.place_order(order)

    def place_order(self, order: OrderCandidate):
        """
        Places a single order
        """
        try:
            if order.order_side == TradeType.BUY:
                self.buy(
                    connector_name=self.config.exchange,
                    trading_pair=order.trading_pair,
                    amount=order.amount,
                    order_type=order.order_type,
                    price=order.price
                )
        except Exception as e:
            self.logger().error(f"Error placing order: {e}")

    def cancel_all_orders(self):
        """
        Cancels all active orders
        """
        try:
            active_orders = self.get_active_orders(connector_name=self.config.exchange)
            if active_orders:
                self.logger().info(f"Cancelling {len(active_orders)} active order(s)")
                for order in active_orders:
                    self.cancel(self.config.exchange, order.trading_pair, order.client_order_id)
                    self.logger().debug(f"Cancelled order {order.client_order_id}")
        except Exception as e:
            self.logger().error(f"Error cancelling orders: {e}")

    def did_fill_order(self, event: OrderFilledEvent):
        """
        Called when an order is filled
        """
        msg = (f"Demo order filled: {event.trade_type.name} {round(event.amount, 4)} {event.trading_pair} "
               f"on {self.config.exchange} at {round(event.price, 4)}")
        self.log_with_clock(logging.INFO, msg)
        self.notify_hb_app_with_timestamp(msg)