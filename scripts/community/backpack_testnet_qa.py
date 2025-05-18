import logging
from decimal import Decimal
from typing import Set

from hummingbot.client.hummingbot_application import HummingbotApplication
from hummingbot.core.data_type.common import OrderType
from hummingbot.core.event.events import BuyOrderCompletedEvent, SellOrderCompletedEvent
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class BackpackTestnetQAStrategy(ScriptStrategyBase):
    """Simple manual QA script for Backpack connector on the testnet.

    Set the ``BACKPACK_API_KEY`` and ``BACKPACK_SECRET_KEY`` environment variables
    before running. The strategy will place a single market order and exit once
    the order is filled.
    """

    exchange: str = "backpack"
    trading_pair: str = "BTC-USDT"
    order_amount: Decimal = Decimal("0.001")
    side: str = "buy"  # "buy" or "sell"

    markets: dict[str, Set[str]] = {exchange: {trading_pair}}

    order_executed: bool = False

    def on_tick(self):
        if not self.order_executed:
            if self.side == "buy":
                self.buy(self.exchange, self.trading_pair, self.order_amount, OrderType.MARKET)
            else:
                self.sell(self.exchange, self.trading_pair, self.order_amount, OrderType.MARKET)
            self.order_executed = True

    def did_complete_buy_order(self, event: BuyOrderCompletedEvent):
        if event.trading_pair == self.trading_pair:
            self.log_with_clock(logging.INFO, f"Buy order {event.order_id} completed.")
            HummingbotApplication.main_application().stop()

    def did_complete_sell_order(self, event: SellOrderCompletedEvent):
        if event.trading_pair == self.trading_pair:
            self.log_with_clock(logging.INFO, f"Sell order {event.order_id} completed.")
            HummingbotApplication.main_application().stop()

