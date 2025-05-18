"""Constants used by the Backpack exchange connector."""

from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit

# Exchange info
EXCHANGE_NAME = "backpack"
DEFAULT_DOMAIN = ""

HBOT_ORDER_ID_PREFIX = "BPX-"
MAX_ORDER_ID_LEN = 32
HBOT_BROKER_ID = "Hummingbot"

# Base URLs
REST_URL = "https://api.backpack.exchange"
WSS_PUBLIC_URL = "wss://ws.backpack.exchange"
WSS_PRIVATE_URL = "wss://ws.backpack.exchange"

# REST API endpoints
ORDER_BOOK_PATH_URL = "/api/v1/depth"
SERVER_TIME_PATH_URL = "/api/v1/time"
MARKETS_PATH_URL = "/api/v1/markets"
TRADES_PATH_URL = "/api/v1/trades"
ORDERS_PATH_URL = "/api/v1/orders"
BALANCE_PATH_URL = "/api/v1/balances"

# Websocket constants
WS_HEARTBEAT_TIME_INTERVAL = 30

# Common API error codes
RATE_LIMIT_ERROR_CODE = 429
AUTHENTICATION_ERROR_CODE = 401
ORDER_NOT_FOUND_ERROR_CODE = 404

# Mapping of API error codes to connector exceptions. Values are names so the
# exchange class can raise meaningful errors when possible.
ERROR_CODE_MAPPING = {
    RATE_LIMIT_ERROR_CODE: "RateLimitError",
    AUTHENTICATION_ERROR_CODE: "AuthenticationError",
    ORDER_NOT_FOUND_ERROR_CODE: "OrderNotFound",
}

# Rate limits (placeholder values)
RATE_LIMITS = [
    # Global per-IP REST limit
    RateLimit(limit_id="REST", limit=100, time_interval=1),
    # Global websocket limit
    RateLimit(limit_id="WEB_SOCKET", limit=30, time_interval=1),
    # Endpoint specific limits linked to REST pool
    RateLimit(
        limit_id=ORDER_BOOK_PATH_URL,
        limit=100,
        time_interval=1,
        linked_limits=[LinkedLimitWeightPair("REST")],
    ),
    RateLimit(
        limit_id=SERVER_TIME_PATH_URL,
        limit=100,
        time_interval=1,
        linked_limits=[LinkedLimitWeightPair("REST")],
    ),
    RateLimit(
        limit_id=MARKETS_PATH_URL,
        limit=100,
        time_interval=1,
        linked_limits=[LinkedLimitWeightPair("REST")],
    ),
    RateLimit(
        limit_id=TRADES_PATH_URL,
        limit=100,
        time_interval=1,
        linked_limits=[LinkedLimitWeightPair("REST")],
    ),
    RateLimit(
        limit_id=ORDERS_PATH_URL,
        limit=100,
        time_interval=1,
        linked_limits=[LinkedLimitWeightPair("REST")],
    ),
    RateLimit(
        limit_id=BALANCE_PATH_URL,
        limit=100,
        time_interval=1,
        linked_limits=[LinkedLimitWeightPair("REST")],
    ),
]
