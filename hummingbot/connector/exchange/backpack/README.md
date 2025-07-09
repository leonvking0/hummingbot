# Backpack Exchange Connector

This is the Hummingbot connector implementation for Backpack Exchange.

## Current Status

✅ **Public API Support** - Order book data, ticker information, and market data
❌ **Private API Support** - Trading functionality not yet implemented

## Features

- Real-time order book updates via WebSocket
- Market data fetching (ticker, trades, depth)
- Trading pair information and rules
- ED25519 authentication support (prepared for future private API implementation)

## Key Implementation Details

### Authentication
Backpack uses ED25519 signatures instead of the more common HMAC-SHA256. The authentication module is implemented and ready for private API support.

### Trading Pair Format
- Backpack format: `SOL_USDC` (underscore separator)
- Hummingbot format: `SOL-USDC` (dash separator)

### Order Book Sorting
Backpack's order book data is not pre-sorted. The connector handles sorting:
- Bids: Sorted by price descending (highest first)
- Asks: Sorted by price ascending (lowest first)

### WebSocket Streams
- Format: `<stream_type>.<symbol>` (e.g., `depth.SOL_USDC`)
- Timestamps are in microseconds (converted to seconds internally)

## Usage Example

```python
from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange

# Create exchange instance (no API keys needed for public data)
exchange = BackpackExchange(
    api_key="",
    api_secret="",
    trading_pairs=["SOL-USDC", "BTC-USDC"],
    trading_required=False
)

# Initialize and fetch trading rules
await exchange._update_trading_rules()

# Access trading rules
for pair, rule in exchange.trading_rules.items():
    print(f"{pair}: min_size={rule.min_order_size}")
```

## Files

- `backpack_constants.py` - Exchange constants and configuration
- `backpack_auth.py` - ED25519 authentication implementation
- `backpack_utils.py` - Utility functions for data conversion
- `backpack_web_utils.py` - Web request helpers
- `backpack_api_order_book_data_source.py` - Order book data handling
- `backpack_exchange.py` - Main exchange connector class

## Testing

Run the test script to verify API connectivity:
```bash
python test_backpack_public_api.py
```

## Future Work

- Implement private API endpoints for trading
- Add user stream data source for account updates
- Implement order placement and cancellation
- Add balance tracking