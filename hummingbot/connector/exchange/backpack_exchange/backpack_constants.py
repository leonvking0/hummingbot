"""Constants used by the Backpack exchange connector."""

from hummingbot.core.api_throttler.data_types import RateLimit

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

# Websocket constants
WS_HEARTBEAT_TIME_INTERVAL = 30

# Rate limits (placeholder values)
RATE_LIMITS = [
    RateLimit(limit_id="REST", limit=100, time_interval=1),
    RateLimit(limit_id="WEB_SOCKET", limit=30, time_interval=1),
]
