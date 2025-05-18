from typing import Dict, Optional

from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType


class BackpackOrderBook(OrderBook):
    """OrderBook with helper methods to create messages from Backpack exchange payloads."""

    @classmethod
    def snapshot_message_from_exchange(
        cls,
        msg: Dict[str, any],
        timestamp: float,
        metadata: Optional[Dict] = None,
    ) -> OrderBookMessage:
        if metadata:
            msg.update(metadata)
        return OrderBookMessage(
            OrderBookMessageType.SNAPSHOT,
            {
                "trading_pair": msg["trading_pair"],
                "update_id": msg["ts"],
                "bids": msg.get("bids", []),
                "asks": msg.get("asks", []),
            },
            timestamp,
        )

    @classmethod
    def diff_message_from_exchange(
        cls,
        msg: Dict[str, any],
        timestamp: Optional[float] = None,
        metadata: Optional[Dict] = None,
    ) -> OrderBookMessage:
        if metadata:
            msg.update(metadata)
        ts = msg.get("ts") or msg.get("t")
        return OrderBookMessage(
            OrderBookMessageType.DIFF,
            {
                "trading_pair": msg["trading_pair"],
                "update_id": ts,
                "bids": msg.get("bids", msg.get("b", [])),
                "asks": msg.get("asks", msg.get("a", [])),
            },
            timestamp or ts,
        )

    @classmethod
    def trade_message_from_exchange(
        cls, msg: Dict[str, any], metadata: Optional[Dict] = None
    ) -> OrderBookMessage:
        if metadata:
            msg.update(metadata)
        ts = msg.get("ts") or msg.get("t")
        side = str(msg.get("side", "buy")).lower()
        trade_type = float(TradeType.BUY.value) if side == "buy" else float(TradeType.SELL.value)
        return OrderBookMessage(
            OrderBookMessageType.TRADE,
            {
                "trading_pair": msg["trading_pair"],
                "trade_type": trade_type,
                "trade_id": ts,
                "update_id": ts,
                "price": msg.get("p") or msg.get("price"),
                "amount": msg.get("q") or msg.get("size"),
            },
            ts,
        )
