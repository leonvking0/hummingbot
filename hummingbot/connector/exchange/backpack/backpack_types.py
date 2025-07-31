"""
Type definitions for Backpack Exchange API responses
"""
from typing import List, Optional, TypedDict


class MarketInfo(TypedDict):
    """Market information from /api/v1/markets"""
    symbol: str
    baseCurrency: str
    quoteCurrency: str
    minOrderSize: str
    tickSize: str
    stepSize: str
    minPrice: str
    maxPrice: str
    minNotional: str
    maxLeverage: str
    baseFee: int
    quoteFee: int
    isSpotAllowed: bool
    status: str


class OrderBookData(TypedDict):
    """Order book data from /api/v1/depth"""
    bids: List[List[str]]  # [[price, amount], ...]
    asks: List[List[str]]  # [[price, amount], ...]
    lastUpdateId: int
    timestamp: int


class TickerData(TypedDict):
    """Ticker data from /api/v1/ticker"""
    symbol: str
    lastPrice: str
    volume: str
    high: str
    low: str
    bid: str
    ask: str
    timestamp: int


class OrderResponse(TypedDict):
    """Order response from /api/v1/order"""
    id: str
    clientOrderId: str
    symbol: str
    side: str  # "Bid" or "Ask"
    orderType: str  # "Limit" or "Market"
    price: str
    quantity: str
    status: str
    executedQuantity: str
    executedQuoteQuantity: str
    timeInForce: str
    timestamp: int


class BalanceData(TypedDict):
    """Balance data from /api/v1/capital or /api/v1/capital/collateral"""
    available: str
    locked: str
    total: str


class CollateralBalance(TypedDict):
    """Collateral balance response"""
    symbol: str
    balance: BalanceData


class TradeData(TypedDict):
    """Trade/fill data"""
    id: str
    orderId: str
    clientOrderId: str
    symbol: str
    side: str
    price: str
    quantity: str
    fee: str
    feeSymbol: str
    timestamp: int


class WebSocketDepthUpdate(TypedDict):
    """WebSocket depth update message"""
    e: str  # Event type: "depth"
    E: int  # Event time (microseconds)
    s: str  # Symbol
    U: int  # First update ID
    u: int  # Final update ID
    b: List[List[str]]  # Bid updates
    a: List[List[str]]  # Ask updates
    T: int  # Transaction time (microseconds)


class WebSocketTradeUpdate(TypedDict):
    """WebSocket trade update message"""
    e: str  # Event type: "trade"
    E: int  # Event time (microseconds)
    s: str  # Symbol
    t: int  # Trade ID
    p: str  # Price
    q: str  # Quantity
    m: bool  # Is buyer maker
    T: int  # Trade time (microseconds)


class WebSocketOrderUpdate(TypedDict):
    """WebSocket order update message"""
    e: str  # Event type: "orderUpdate"
    E: int  # Event time (microseconds)
    s: str  # Symbol
    c: str  # Client order ID
    S: str  # Side
    o: str  # Order type
    f: str  # Time in force
    q: str  # Order quantity
    p: str  # Order price
    P: str  # Stop price (optional)
    x: str  # Current execution type
    X: str  # Current order status
    i: str  # Order ID
    l: str  # Last executed quantity
    z: str  # Cumulative filled quantity
    L: str  # Last executed price
    n: str  # Commission amount
    N: Optional[str]  # Commission asset
    T: int  # Transaction time (microseconds)
    t: int  # Trade ID
    O: int  # Order creation time
    Z: str  # Cumulative quote asset transacted quantity
    Y: str  # Last quote asset transacted quantity (last filled price * last filled quantity)
    Q: str  # Quote order quantity