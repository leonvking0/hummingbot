from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ConfigDict, Field, SecretStr

from hummingbot.client.config.config_data_types import BaseConnectorConfigMap
from hummingbot.connector.derivative.backpack_perpetual import backpack_perpetual_constants as CONSTANTS
from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.order_book_row import OrderBookRow
from hummingbot.core.data_type.trade_fee import TokenAmount, TradeFeeBase, TradeFeeSchema

# Backpack fees: https://backpack.exchange/refer/fee-schedule
DEFAULT_FEES = TradeFeeSchema(
    maker_percent_fee_decimal=Decimal("0.0002"),  # 0.02% maker fee
    taker_percent_fee_decimal=Decimal("0.0005"),  # 0.05% taker fee
)

CENTRALIZED = True

EXAMPLE_PAIR = "BTC-USDC-PERP"


def split_trading_pair(trading_pair: str) -> tuple[str, str]:
    """
    Split a trading pair into base and quote assets
    For perpetuals, format is BASE-QUOTE-PERP (Hummingbot format) or BASE_QUOTE_PERP (Exchange format)
    """
    # Try splitting with dash first (Hummingbot format)
    parts = trading_pair.split("-")
    if len(parts) >= 3 and parts[-1] == "PERP":
        # Remove the PERP suffix and return base/quote
        return parts[0], parts[1]
    elif len(parts) == 2:
        return parts[0], parts[1]
    
    # Try splitting with underscore (Exchange format)
    parts = trading_pair.split("_")
    if len(parts) >= 3 and parts[-1] == "PERP":
        # Remove the PERP suffix and return base/quote
        return parts[0], parts[1]
    elif len(parts) == 2:
        return parts[0], parts[1]
    
    raise ValueError(f"Invalid trading pair format: {trading_pair}")


def convert_from_exchange_trading_pair(exchange_trading_pair: str) -> str:
    """
    Convert from exchange format to Hummingbot format
    Exchange uses underscores: BTC_USDC_PERP
    Hummingbot uses dashes: BTC-USDC-PERP
    """
    return exchange_trading_pair.replace("_", "-")


def convert_to_exchange_trading_pair(hb_trading_pair: str) -> str:
    """
    Convert from Hummingbot format to exchange format
    Hummingbot uses dashes: BTC-USDC-PERP
    Exchange uses underscores: BTC_USDC_PERP
    """
    return hb_trading_pair.replace("-", "_")


def get_new_perp_client_order_id(
    is_buy: bool,
    trading_pair: str,
    current_timestamp: float
) -> str:
    """
    Generate a client order ID for perpetual orders
    Backpack uses numeric client order IDs (uint32)
    """
    # Use timestamp modulo to ensure it fits in uint32 range
    timestamp_int = int(current_timestamp * 1000) % (2**32)
    return str(timestamp_int)


def parse_trading_rule(market_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse trading rule from market info for perpetual contracts
    """
    filters = market_info.get("filters", {})
    price_filter = filters.get("price", {})
    quantity_filter = filters.get("quantity", {})
    
    # Extract contract multiplier if available
    contract_multiplier = Decimal(str(market_info.get("contractMultiplier", "1")))
    
    return {
        "min_order_size": Decimal(str(quantity_filter.get("minQuantity", "0.00000001"))),
        "max_order_size": Decimal(str(quantity_filter.get("maxQuantity", "999999999"))),
        "min_price_increment": Decimal(str(price_filter.get("tickSize", "0.00000001"))),
        "min_base_amount_increment": Decimal(str(quantity_filter.get("stepSize", "0.00000001"))),
        "min_quote_amount_increment": Decimal(str(price_filter.get("tickSize", "0.00000001"))),
        "min_notional_size": Decimal(str(filters.get("notional", {}).get("minNotional", "0"))),
        "max_leverage": Decimal(str(market_info.get("maxLeverage", CONSTANTS.MAX_LEVERAGE))),
        "contract_multiplier": contract_multiplier,
        "supports_limit_orders": True,
        "supports_market_orders": True,
    }


def parse_order_book_snapshot(
    snapshot_data: Dict[str, Any],
    trading_pair: str,
    timestamp: float
) -> OrderBookMessage:
    """
    Parse order book snapshot data
    Note: Backpack order books may be unsorted
    """
    # Backpack returns bids and asks in the data directly
    bids = snapshot_data.get("bids", [])
    asks = snapshot_data.get("asks", [])
    
    # Convert to OrderBookRow format and sort
    bid_rows = []
    for bid in bids:
        price = Decimal(str(bid[0]))
        amount = Decimal(str(bid[1]))
        bid_rows.append(OrderBookRow(price, amount, snapshot_data.get("lastUpdateId", 0)))
    
    ask_rows = []
    for ask in asks:
        price = Decimal(str(ask[0]))
        amount = Decimal(str(ask[1]))
        ask_rows.append(OrderBookRow(price, amount, snapshot_data.get("lastUpdateId", 0)))
    
    # Sort the order books (important for Backpack!)
    bid_rows.sort(key=lambda x: x.price, reverse=True)
    ask_rows.sort(key=lambda x: x.price)
    
    return OrderBookMessage(
        message_type=OrderBookMessageType.SNAPSHOT,
        content={
            "trading_pair": trading_pair,
            "bids": bid_rows,
            "asks": ask_rows,
            "update_id": snapshot_data.get("lastUpdateId", int(timestamp * 1000)),
        },
        timestamp=timestamp
    )


def parse_order_book_diff(
    diff_data: Dict[str, Any],
    trading_pair: str,
    timestamp: float
) -> OrderBookMessage:
    """
    Parse order book diff/update data
    """
    bids = diff_data.get("b", [])
    asks = diff_data.get("a", [])
    
    bid_rows = []
    for bid in bids:
        price = Decimal(str(bid[0]))
        amount = Decimal(str(bid[1]))
        bid_rows.append(OrderBookRow(price, amount, diff_data.get("u", 0)))
    
    ask_rows = []
    for ask in asks:
        price = Decimal(str(ask[0]))
        amount = Decimal(str(ask[1]))
        ask_rows.append(OrderBookRow(price, amount, diff_data.get("u", 0)))
    
    # Sort the updates
    bid_rows.sort(key=lambda x: x.price, reverse=True)
    ask_rows.sort(key=lambda x: x.price)
    
    return OrderBookMessage(
        message_type=OrderBookMessageType.DIFF,
        content={
            "trading_pair": trading_pair,
            "bids": bid_rows,
            "asks": ask_rows,
            "update_id": diff_data.get("u", int(timestamp * 1000)),
            "first_update_id": diff_data.get("U", diff_data.get("u", int(timestamp * 1000))),
        },
        timestamp=timestamp
    )


def parse_funding_info(funding_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse funding rate information
    """
    return {
        "funding_rate": Decimal(str(funding_data.get("fundingRate", "0"))),
        "next_funding_timestamp": funding_data.get("nextFundingTime", 0) / 1000,  # Convert to seconds
        "funding_interval": funding_data.get("fundingInterval", CONSTANTS.FUNDING_RATE_INTERVAL_HOURS * 3600),
    }


def parse_trade_fee(
    trade_fee_data: Dict[str, Any],
    order_side: TradeType,
    is_maker: bool
) -> TradeFeeBase:
    """
    Parse trade fee from exchange data
    For perpetuals, fees are typically in the quote currency
    """
    # Backpack might provide maker/taker fees
    if is_maker:
        fee_rate = Decimal(str(trade_fee_data.get("makerFee", "0.0002")))  # 0.02% default
    else:
        fee_rate = Decimal(str(trade_fee_data.get("takerFee", "0.0005")))  # 0.05% default
    
    # For perpetuals, fees are usually in the quote currency
    # The actual fee amount would be calculated based on the trade
    return TradeFeeBase.new_perpetual_fee(
        fee_schema=TradeFeeSchema(),
        trade_type=order_side,
        percent=fee_rate * Decimal("100"),  # Convert to percentage
        flat_fees=[]
    )


def is_exchange_information_valid(market_info: Dict[str, Any]) -> bool:
    """
    Check if the market info is valid for a perpetual market
    """
    return (
        market_info.get("status") == "ONLINE" and
        market_info.get("marketType") in CONSTANTS.PERPETUAL_MARKET_TYPES and
        market_info.get("symbol") is not None
    )


def parse_position_info(position_data: Dict[str, Any], trading_pair: str) -> Dict[str, Any]:
    """
    Parse position information from API response
    """
    # Determine position side from quantity (negative = short)
    quantity = Decimal(str(position_data.get("q", "0")))
    position_side = "LONG" if quantity >= 0 else "SHORT"
    
    return {
        "trading_pair": trading_pair,
        "position_side": position_side,
        "unrealized_pnl": Decimal(str(position_data.get("P", "0"))),
        "entry_price": Decimal(str(position_data.get("B", "0"))),
        "amount": abs(quantity),  # Always positive
        "leverage": Decimal(str(position_data.get("leverage", "1"))),
        "liquidation_price": Decimal(str(position_data.get("l", "0"))),
        "mark_price": Decimal(str(position_data.get("M", "0"))),
    }


def get_account_id_from_trading_pair(trading_pair: str) -> str:
    """
    Get account ID for position tracking
    For now, return a default account ID
    """
    return "default"


def decimal_val_or_none(value: Any) -> Optional[Decimal]:
    """
    Convert value to Decimal or return None
    """
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def get_next_funding_timestamp(current_timestamp: float) -> float:
    """
    Calculate next funding timestamp
    Backpack funding occurs every 8 hours
    """
    int_ts = int(current_timestamp)
    eight_hours = CONSTANTS.FUNDING_RATE_INTERVAL_HOURS * 60 * 60
    mod = int_ts % eight_hours
    return float(int_ts - mod + eight_hours)


class BackpackPerpetualConfigMap(BaseConnectorConfigMap):
    connector: str = "backpack_perpetual"
    backpack_perpetual_api_key: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Backpack Perpetual API key (public key)",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    backpack_perpetual_api_secret: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Backpack Perpetual API secret (private key)", 
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        },
    )
    model_config = ConfigDict(title="backpack_perpetual")


KEYS = BackpackPerpetualConfigMap.model_construct()

# Testnet configuration (if Backpack provides testnet)
OTHER_DOMAINS = ["backpack_perpetual_testnet"]
OTHER_DOMAINS_PARAMETER = {"backpack_perpetual_testnet": "backpack_perpetual_testnet"}
OTHER_DOMAINS_EXAMPLE_PAIR = {"backpack_perpetual_testnet": "BTC-USDC-PERP"}
OTHER_DOMAINS_DEFAULT_FEES = {
    "backpack_perpetual_testnet": TradeFeeSchema(
        maker_percent_fee_decimal=Decimal("0.0002"),
        taker_percent_fee_decimal=Decimal("0.0005"),
    )
}


class BackpackPerpetualTestnetConfigMap(BaseConnectorConfigMap):
    connector: str = "backpack_perpetual_testnet"
    backpack_perpetual_testnet_api_key: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Backpack Perpetual Testnet API key (public key)",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    backpack_perpetual_testnet_api_secret: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Backpack Perpetual Testnet API secret (private key)",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        },
    )
    model_config = ConfigDict(title="backpack_perpetual_testnet")


OTHER_DOMAINS_KEYS = {
    "backpack_perpetual_testnet": BackpackPerpetualTestnetConfigMap.model_construct()
}