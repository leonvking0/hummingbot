from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import OrderState
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.order_book_row import OrderBookRow
from hummingbot.core.data_type.trade_fee import TradeFeeBase, TradeFeeSchema


def split_trading_pair(trading_pair: str) -> Optional[Tuple[str, str]]:
    """
    Split a Hummingbot trading pair into base and quote assets

    :param trading_pair: Trading pair in Hummingbot format (e.g., "SOL-USDC")
    :return: Tuple of (base_asset, quote_asset) or None if invalid
    """
    try:
        if "-" in trading_pair:
            base, quote = trading_pair.split("-")
            return base, quote
        return None
    except Exception:
        return None


def convert_to_exchange_trading_pair(
    hummingbot_trading_pair: str,
    delimiter: str = CONSTANTS.TRADING_PAIR_SPLITTER
) -> str:
    """
    Convert Hummingbot trading pair format to Backpack exchange format

    :param hummingbot_trading_pair: Trading pair in Hummingbot format (e.g., "SOL-USDC")
    :param delimiter: The delimiter used by the exchange (default: "_")
    :return: Trading pair in exchange format (e.g., "SOL_USDC")
    """
    return hummingbot_trading_pair.replace("-", delimiter)


def convert_from_exchange_trading_pair(
    exchange_trading_pair: str,
    delimiter: str = CONSTANTS.TRADING_PAIR_SPLITTER
) -> str:
    """
    Convert Backpack exchange trading pair format to Hummingbot format

    :param exchange_trading_pair: Trading pair in exchange format (e.g., "SOL_USDC")
    :param delimiter: The delimiter used by the exchange (default: "_")
    :return: Trading pair in Hummingbot format (e.g., "SOL-USDC")
    """
    return exchange_trading_pair.replace(delimiter, "-")


def convert_order_type(order_type: OrderType) -> str:
    """
    Convert Hummingbot order type to Backpack order type

    :param order_type: Hummingbot OrderType enum
    :return: Backpack order type string
    """
    return CONSTANTS.ORDER_TYPE_MAP.get(order_type, "Limit")


def convert_trade_type(trade_type: TradeType) -> str:
    """
    Convert Hummingbot trade type to Backpack side

    :param trade_type: Hummingbot TradeType enum
    :return: Backpack side string ("Bid" or "Ask")
    """
    return CONSTANTS.TRADE_TYPE_MAP.get(trade_type, "Bid")


def convert_order_state(order_status: str) -> OrderState:
    """
    Convert Backpack order status to Hummingbot order state

    :param order_status: Backpack order status string
    :return: Hummingbot OrderState enum
    """
    return CONSTANTS.ORDER_STATE_MAP.get(order_status, OrderState.OPEN)


def get_new_client_order_id(
    is_buy: bool,
    trading_pair: str,
    max_id_bit_count: Optional[int] = None
) -> int:
    """
    Generate a new client order ID

    :param is_buy: Whether this is a buy order
    :param trading_pair: The trading pair
    :param max_id_bit_count: Maximum bit count for the ID
    :return: New client order ID as integer
    """
    # Backpack accepts uint32 for client ID, which is 32 bits
    if max_id_bit_count is None:
        max_id_bit_count = 32
    
    # Use timestamp with some randomness, ensuring it fits in uint32
    import time
    import random
    timestamp = int(time.time() * 1000) % (2**30)  # Leave room for random bits
    random_bits = random.randint(0, 2**(max_id_bit_count - 30) - 1)
    
    return (timestamp << 2) | random_bits


def parse_order_book_snapshot(
    snapshot_data: Dict[str, Any],
    trading_pair: str,
    timestamp: float
) -> OrderBookMessage:
    """
    Parse order book snapshot data into OrderBookMessage

    :param snapshot_data: Raw order book data from the API
    :param trading_pair: The trading pair
    :param timestamp: Message timestamp
    :return: OrderBookMessage object
    """
    bids = []
    asks = []
    
    # Get update_id from snapshot data or use timestamp as integer
    update_id = int(snapshot_data.get("lastUpdateId", int(timestamp * 1000)))
    
    # Parse and sort bids (highest price first)
    raw_bids = snapshot_data.get("bids", [])
    sorted_bids = sorted(raw_bids, key=lambda x: float(x[0]), reverse=True)
    for bid in sorted_bids:
        price = Decimal(str(bid[0]))
        amount = Decimal(str(bid[1]))
        bids.append(OrderBookRow(price, amount, update_id))
    
    # Parse and sort asks (lowest price first)
    raw_asks = snapshot_data.get("asks", [])
    sorted_asks = sorted(raw_asks, key=lambda x: float(x[0]))
    for ask in sorted_asks:
        price = Decimal(str(ask[0]))
        amount = Decimal(str(ask[1]))
        asks.append(OrderBookRow(price, amount, update_id))
    
    return OrderBookMessage(
        message_type=OrderBookMessageType.SNAPSHOT,
        content={
            "trading_pair": trading_pair,
            "bids": bids,
            "asks": asks,
            "update_id": update_id
        },
        timestamp=timestamp
    )


def parse_order_book_diff(
    diff_data: Dict[str, Any],
    trading_pair: str,
    timestamp: float
) -> OrderBookMessage:
    """
    Parse order book diff/update data into OrderBookMessage

    :param diff_data: Raw order book diff data from WebSocket
    :param trading_pair: The trading pair
    :param timestamp: Message timestamp
    :return: OrderBookMessage object
    """
    bids = []
    asks = []
    
    # Get update_id from diff data or use timestamp as integer
    update_id = int(diff_data.get("u", int(timestamp * 1000)))
    first_update_id = int(diff_data.get("U", update_id))
    
    # Parse bid updates
    for bid in diff_data.get("b", []):
        price = Decimal(str(bid[0]))
        amount = Decimal(str(bid[1]))
        bids.append(OrderBookRow(price, amount, update_id))
    
    # Parse ask updates
    for ask in diff_data.get("a", []):
        price = Decimal(str(ask[0]))
        amount = Decimal(str(ask[1]))
        asks.append(OrderBookRow(price, amount, update_id))
    
    return OrderBookMessage(
        message_type=OrderBookMessageType.DIFF,
        content={
            "trading_pair": trading_pair,
            "bids": bids,
            "asks": asks,
            "update_id": update_id,
            "first_update_id": first_update_id
        },
        timestamp=timestamp
    )


def parse_trade_fee(
    fee_data: Dict[str, Any],
    trade_type: TradeType,
    is_maker: bool = True
) -> TradeFeeBase:
    """
    Parse trade fee data

    :param fee_data: Fee data from the exchange
    :param trade_type: The trade type (buy/sell)
    :param is_maker: Whether this is a maker fee
    :return: TradeFeeBase object
    """
    # Default fee structure if not provided
    # Backpack typical fees: 0.04% maker, 0.10% taker
    if not fee_data:
        percent = Decimal("0.0004") if is_maker else Decimal("0.001")
    else:
        percent = Decimal(str(fee_data.get("fee", "0")))
    
    return TradeFeeBase(
        trading_pair="",  # Will be set by the caller
        percent=percent,
        flat_fees=[]  # Backpack doesn't have flat fees
    )


def is_valid_trading_pair(trading_pair: str) -> bool:
    """
    Check if a trading pair string is valid

    :param trading_pair: The trading pair to validate
    :return: True if valid, False otherwise
    """
    parts = trading_pair.split(CONSTANTS.TRADING_PAIR_SPLITTER)
    return len(parts) == 2 and all(part for part in parts)