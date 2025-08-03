import sys
from enum import Enum
from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import OrderState

EXCHANGE_NAME = "backpack"

# Base URLs
DEFAULT_DOMAIN = "backpack"
REST_URL = "https://api.backpack.exchange"
WSS_URL = "wss://ws.backpack.exchange"

# Public API endpoints
MARKETS_PATH_URL = "/api/v1/markets"
MARKET_PATH_URL = "/api/v1/market"
TICKER_PATH_URL = "/api/v1/ticker"
TICKERS_PATH_URL = "/api/v1/tickers"
DEPTH_PATH_URL = "/api/v1/depth"
TRADES_PATH_URL = "/api/v1/trades"
KLINES_PATH_URL = "/api/v1/klines"

# Private API endpoints (for future implementation)
ACCOUNT_PATH_URL = "/api/v1/account"
BALANCES_PATH_URL = "/api/v1/capital"
COLLATERAL_PATH_URL = "/api/v1/capital/collateral"
ORDER_PATH_URL = "/api/v1/order"
ORDERS_PATH_URL = "/api/v1/orders"
FILLS_PATH_URL = "/api/v1/fills"

# WebSocket stream names
WS_DEPTH_STREAM = "depth"
WS_TICKER_STREAM = "ticker"
WS_TRADES_STREAM = "trade"
WS_BOOK_TICKER_STREAM = "bookTicker"

# Order states mapping
ORDER_STATE_MAP = {
    "New": OrderState.OPEN,
    "PartiallyFilled": OrderState.PARTIALLY_FILLED,
    "Filled": OrderState.FILLED,
    "Cancelled": OrderState.CANCELED,
    "Expired": OrderState.CANCELED,
    "TriggerPending": OrderState.PENDING_CREATE,
    "TriggerFailed": OrderState.FAILED,
}

# Order book states that indicate active trading
# Based on actual API response: Open, Closed, PostOnly
ACTIVE_ORDER_BOOK_STATES = ["Open"]

# Rate Limits
# Using conservative limits as exact values not specified in API doc
RATE_LIMITS = [
    RateLimit(limit_id=MARKETS_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=TICKER_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=DEPTH_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=TRADES_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=KLINES_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=ACCOUNT_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=BALANCES_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=COLLATERAL_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=ORDER_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=ORDERS_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=FILLS_PATH_URL, limit=10, time_interval=1),
]

# Trading pair conversion
TRADING_PAIR_SPLITTER = "_"

# Order types
ORDER_TYPE_MAP = {
    OrderType.LIMIT: "Limit",
    OrderType.MARKET: "Market",
}

# Trade types
TRADE_TYPE_MAP = {
    TradeType.BUY: "Bid",
    TradeType.SELL: "Ask",
}

# Time in force
TIME_IN_FORCE_MAP = {
    "GTC": "GTC",  # Good Till Cancelled
    "IOC": "IOC",  # Immediate or Cancel
    "FOK": "FOK",  # Fill or Kill
}

# Default parameters
DEFAULT_TIME_IN_FORCE = "GTC"
DEFAULT_DOMAIN = "backpack"

# WebSocket parameters
WS_HEARTBEAT_INTERVAL = 30  # Send ping every 30 seconds
WS_HEARTBEAT_TIMEOUT = 60   # Timeout if no pong received in 60 seconds

# API request headers
HEADER_API_KEY = "X-API-KEY"
HEADER_SIGNATURE = "X-SIGNATURE"
HEADER_TIMESTAMP = "X-TIMESTAMP"
HEADER_WINDOW = "X-WINDOW"

# Default request window (milliseconds)
DEFAULT_REQUEST_WINDOW = 1000
MAX_REQUEST_WINDOW = 5000

# Order book depth limit
ORDER_BOOK_DEPTH_LIMIT = 1000

# Numeric precision
# This should be updated based on actual market data
DEFAULT_PRICE_DECIMALS = 8
DEFAULT_QUANTITY_DECIMALS = 8

# Backpack API Error Codes
class BackpackErrorCode(Enum):
    """Backpack Exchange API error codes"""
    ACCOUNT_LIQUIDATING = "ACCOUNT_LIQUIDATING"
    BORROW_LIMIT = "BORROW_LIMIT"
    BORROW_REQUIRES_LEND_REDEEM = "BORROW_REQUIRES_LEND_REDEEM"
    FORBIDDEN = "FORBIDDEN"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    INSUFFICIENT_SUPPLY = "INSUFFICIENT_SUPPLY"
    INVALID_ASSET = "INVALID_ASSET"
    INVALID_CLIENT_REQUEST = "INVALID_CLIENT_REQUEST"
    INVALID_MARKET = "INVALID_MARKET"
    INVALID_ORDER = "INVALID_ORDER"
    INVALID_PRICE = "INVALID_PRICE"
    INVALID_POSITION_ID = "INVALID_POSITION_ID"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    INVALID_RANGE = "INVALID_RANGE"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    INVALID_SOURCE = "INVALID_SOURCE"
    INVALID_SYMBOL = "INVALID_SYMBOL"
    INVALID_TWO_FACTOR_CODE = "INVALID_TWO_FACTOR_CODE"
    LEND_LIMIT = "LEND_LIMIT"
    LEND_REQUIRES_BORROW_REPAY = "LEND_REQUIRES_BORROW_REPAY"
    MAINTENANCE = "MAINTENANCE"
    MAX_LEVERAGE_REACHED = "MAX_LEVERAGE_REACHED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    ORDER_LIMIT = "ORDER_LIMIT"
    POSITION_LIMIT = "POSITION_LIMIT"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    SERVER_ERROR = "SERVER_ERROR"
    TIMEOUT = "TIMEOUT"
    TOO_MANY_REQUESTS = "TOO_MANY_REQUESTS"
    TRADING_PAUSED = "TRADING_PAUSED"
    UNAUTHORIZED = "UNAUTHORIZED"

# Error code to exception message mapping
ERROR_CODE_MESSAGES = {
    BackpackErrorCode.ACCOUNT_LIQUIDATING: "Account is currently being liquidated",
    BackpackErrorCode.BORROW_LIMIT: "Borrow limit exceeded",
    BackpackErrorCode.BORROW_REQUIRES_LEND_REDEEM: "Borrow requires lend redeem",
    BackpackErrorCode.FORBIDDEN: "Access forbidden - check permissions",
    BackpackErrorCode.INSUFFICIENT_FUNDS: "Insufficient funds for this operation",
    BackpackErrorCode.INSUFFICIENT_MARGIN: "Insufficient margin for this order",
    BackpackErrorCode.INSUFFICIENT_SUPPLY: "Insufficient supply available",
    BackpackErrorCode.INVALID_ASSET: "Invalid asset specified",
    BackpackErrorCode.INVALID_CLIENT_REQUEST: "Invalid client request format",
    BackpackErrorCode.INVALID_MARKET: "Invalid market specified",
    BackpackErrorCode.INVALID_ORDER: "Invalid order - order not found or already cancelled",
    BackpackErrorCode.INVALID_PRICE: "Invalid price specified",
    BackpackErrorCode.INVALID_POSITION_ID: "Invalid position ID",
    BackpackErrorCode.INVALID_QUANTITY: "Invalid quantity specified",
    BackpackErrorCode.INVALID_RANGE: "Invalid range specified",
    BackpackErrorCode.INVALID_SIGNATURE: "Invalid signature - check API credentials",
    BackpackErrorCode.INVALID_SOURCE: "Invalid source specified",
    BackpackErrorCode.INVALID_SYMBOL: "Invalid trading pair symbol",
    BackpackErrorCode.INVALID_TWO_FACTOR_CODE: "Invalid two-factor authentication code",
    BackpackErrorCode.LEND_LIMIT: "Lend limit exceeded",
    BackpackErrorCode.LEND_REQUIRES_BORROW_REPAY: "Lend requires borrow repay",
    BackpackErrorCode.MAINTENANCE: "Exchange is under maintenance",
    BackpackErrorCode.MAX_LEVERAGE_REACHED: "Maximum leverage reached",
    BackpackErrorCode.NOT_IMPLEMENTED: "Feature not implemented",
    BackpackErrorCode.ORDER_LIMIT: "Order limit exceeded",
    BackpackErrorCode.POSITION_LIMIT: "Position limit exceeded",
    BackpackErrorCode.PRECONDITION_FAILED: "Precondition failed for this operation",
    BackpackErrorCode.RESOURCE_NOT_FOUND: "Resource not found",
    BackpackErrorCode.SERVER_ERROR: "Internal server error - please try again",
    BackpackErrorCode.TIMEOUT: "Request timeout",
    BackpackErrorCode.TOO_MANY_REQUESTS: "Rate limit exceeded - too many requests",
    BackpackErrorCode.TRADING_PAUSED: "Trading is currently paused",
    BackpackErrorCode.UNAUTHORIZED: "Unauthorized - check API credentials",
}

# Error codes that indicate order not found during cancellation
ORDER_NOT_FOUND_ERRORS = {
    BackpackErrorCode.INVALID_ORDER,
    BackpackErrorCode.RESOURCE_NOT_FOUND,
}

# Valid order state transitions
VALID_ORDER_STATE_TRANSITIONS = {
    OrderState.PENDING_CREATE: [OrderState.OPEN, OrderState.FAILED, OrderState.CANCELED],
    OrderState.OPEN: [OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELED, OrderState.FAILED],
    OrderState.PARTIALLY_FILLED: [OrderState.FILLED, OrderState.CANCELED, OrderState.FAILED],
    OrderState.FILLED: [],  # Terminal state
    OrderState.CANCELED: [],  # Terminal state
    OrderState.FAILED: [],  # Terminal state
    # PENDING_CANCEL can transition back to previous state if cancellation fails
    OrderState.PENDING_CANCEL: [OrderState.CANCELED, OrderState.OPEN, OrderState.PARTIALLY_FILLED],
}