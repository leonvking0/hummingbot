import sys
from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import OrderState

EXCHANGE_NAME = "backpack_perpetual"

# Base URLs
DEFAULT_DOMAIN = "backpack_perpetual"
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
FUNDING_RATE_PATH_URL = "/api/v1/fundingRate"
FUNDING_RATES_PATH_URL = "/api/v1/fundingRates"
OPEN_INTEREST_PATH_URL = "/api/v1/openInterest"

# Private API endpoints
ACCOUNT_PATH_URL = "/api/v1/account"
BALANCES_PATH_URL = "/api/v1/capital"
ORDER_PATH_URL = "/api/v1/order"
ORDERS_PATH_URL = "/api/v1/orders"
FILLS_PATH_URL = "/api/v1/fills"
POSITIONS_PATH_URL = "/api/v1/positions"
FUNDING_HISTORY_PATH_URL = "/api/v1/history/funding"
PNL_HISTORY_PATH_URL = "/api/v1/history/pnl"

# WebSocket stream names
WS_DEPTH_STREAM = "depth"
WS_TICKER_STREAM = "ticker"
WS_TRADES_STREAM = "trade"
WS_BOOK_TICKER_STREAM = "bookTicker"
WS_FUNDING_RATE_STREAM = "fundingRate"
WS_OPEN_INTEREST_STREAM = "openInterest"

# Private WebSocket streams
WS_ACCOUNT_ORDER_UPDATE_STREAM = "account.orderUpdate"
WS_ACCOUNT_POSITION_UPDATE_STREAM = "account.positionUpdate"

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

# Rate Limits
RATE_LIMITS = [
    RateLimit(limit_id=MARKETS_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=TICKER_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=DEPTH_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=TRADES_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=KLINES_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=FUNDING_RATE_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=FUNDING_RATES_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=OPEN_INTEREST_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=ACCOUNT_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=BALANCES_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=ORDER_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=ORDERS_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=FILLS_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=POSITIONS_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=FUNDING_HISTORY_PATH_URL, limit=10, time_interval=1),
    RateLimit(limit_id=PNL_HISTORY_PATH_URL, limit=10, time_interval=1),
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
DEFAULT_DOMAIN = "backpack_perpetual"

# WebSocket parameters
WS_HEARTBEAT_INTERVAL = 30  # Send ping every 30 seconds
WS_HEARTBEAT_TIMEOUT = 60   # Timeout if no pong received in 60 seconds

# API request headers
HEADER_API_KEY = "X-API-KEY"
HEADER_SIGNATURE = "X-SIGNATURE"
HEADER_TIMESTAMP = "X-TIMESTAMP"
HEADER_WINDOW = "X-WINDOW"

# Default request window (milliseconds)
DEFAULT_REQUEST_WINDOW = 5000
MAX_REQUEST_WINDOW = 60000

# Order book depth limit
ORDER_BOOK_DEPTH_LIMIT = 1000

# Numeric precision
DEFAULT_PRICE_DECIMALS = 8
DEFAULT_QUANTITY_DECIMALS = 8

# Perpetual-specific constants
FUNDING_RATE_INTERVAL_HOURS = 8  # Funding rate interval in hours
DEFAULT_LEVERAGE = 1
MAX_LEVERAGE = 20

# Position modes
POSITION_MODE_ONEWAY = "ONEWAY"
POSITION_MODE_HEDGE = "HEDGE"

# Market types to filter for perpetuals
PERPETUAL_MARKET_TYPES = ["PERP", "IPERP"]  # Regular and inverse perpetuals

# Error codes
ERROR_CODES = {
    "INVALID_ORDER": "Invalid order parameters",
    "RESOURCE_NOT_FOUND": "Order not found",
    "INSUFFICIENT_BALANCE": "Insufficient balance",
    "INVALID_SIGNATURE": "Invalid signature",
}