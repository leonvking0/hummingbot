import logging
import os
from decimal import Decimal
from typing import Dict, List

from pydantic import Field

from hummingbot.client.config.config_data_types import BaseClientModel
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import OrderType, PriceType, TradeType
from hummingbot.core.data_type.order_candidate import OrderCandidate
from hummingbot.core.event.events import OrderFilledEvent
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class BackpackSimpleBuyConfig(BaseClientModel):
    script_file_name: str = os.path.basename(__file__)
    exchange: str = Field("backpack")
    trading_pair: str = Field("SOL-USDC")
    order_amount: Decimal = Field(Decimal("0.1"))
    price_discount: Decimal = Field(Decimal("0.1"))  # 10% discount from mid price
    order_refresh_time: int = Field(60)  # Cancel and replace every 60 seconds


class BackpackSimpleBuy(ScriptStrategyBase):
    """
    Simple trading algorithm for Backpack exchange that:
    1. Places a buy order 10% below the current mid price
    2. Cancels and replaces the order every minute if unfilled
    3. Trades 0.1 SOL by default
    """

    # Define markets as a class attribute
    markets = {}
    create_timestamp = 0

    @classmethod
    def init_markets(cls, config: BackpackSimpleBuyConfig):
        cls.markets = {config.exchange: {config.trading_pair}}

    def __init__(self, connectors: Dict[str, ConnectorBase], config: BackpackSimpleBuyConfig):
        super().__init__(connectors)
        self.config = config

    def on_tick(self):
        """
        Called every second. Checks if it's time to refresh orders.
        """
        if self.create_timestamp <= self.current_timestamp:
            # Cancel all existing orders
            self.cancel_all_orders()
            
            # Create and place new order
            proposal = self.create_proposal()
            if proposal:
                proposal_adjusted = self.adjust_proposal_to_budget(proposal)
                if proposal_adjusted:
                    self.place_orders(proposal_adjusted)
                    self.logger().info(f"Placed buy order for {self.config.order_amount} SOL at "
                                     f"{(1 - self.config.price_discount) * 100}% of mid price")
                else:
                    self.logger().warning("Insufficient balance to place order")
            
            # Set next refresh time
            self.create_timestamp = self.config.order_refresh_time + self.current_timestamp

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
            proposal_adjusted = self.connectors[self.config.exchange].budget_checker.adjust_candidates(
                proposal, 
                all_or_none=True
            )
            return proposal_adjusted
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
            for order in active_orders:
                self.cancel(self.config.exchange, order.trading_pair, order.client_order_id)
                self.logger().info(f"Cancelled order {order.client_order_id}")
        except Exception as e:
            self.logger().error(f"Error cancelling orders: {e}")

    def did_fill_order(self, event: OrderFilledEvent):
        """
        Called when an order is filled
        """
        msg = (f"Order filled: {event.trade_type.name} {round(event.amount, 4)} {event.trading_pair} "
               f"on {self.config.exchange} at {round(event.price, 4)}")
        self.log_with_clock(logging.INFO, msg)
        self.notify_hb_app_with_timestamp(msg)