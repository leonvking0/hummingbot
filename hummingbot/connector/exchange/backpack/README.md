# Backpack Exchange Connector

This is the Hummingbot connector implementation for Backpack Exchange, a high-performance cryptocurrency exchange built by the team behind the Backpack wallet.

## Overview

Backpack Exchange is a centralized cryptocurrency exchange that offers spot trading with a focus on performance and reliability. This connector enables automated trading on Backpack Exchange through Hummingbot.

## Current Status

✅ **Public API Support** - Order book data, ticker information, and market data  
✅ **Private API Support** - Full trading functionality with authentication  
✅ **WebSocket Support** - Real-time market data streaming  
✅ **Demo Mode** - Paper trading when no API credentials provided  

## Features

### Core Features
- Full spot trading support (limit and market orders)
- Real-time order book updates via WebSocket
- Trading pair information and dynamic trading rules
- Balance tracking and order management
- ED25519 signature-based authentication
- Automatic WebSocket reconnection with exponential backoff
- Connection health monitoring and stale connection detection

### Reliability Features
- **Exponential Backoff Reconnection**: Automatically reconnects to WebSocket with increasing delays (1s → 2s → 4s → ... → 60s max)
- **Connection Health Monitoring**: Detects stale connections and forces reconnection if no messages received for 2 minutes
- **Comprehensive Error Handling**: Graceful handling of network issues and API errors

## Key Implementation Details

### Authentication
Backpack uses ED25519 signatures for API authentication instead of the more common HMAC-SHA256. This provides enhanced security and performance.

**Setting up API Keys:**
1. Log in to your Backpack Exchange account
2. Navigate to API settings
3. Create a new API key pair
4. Store your API secret securely (base64 encoded private key)

### Trading Pair Format
- Backpack format: `SOL_USDC` (underscore separator)
- Hummingbot format: `SOL-USDC` (dash separator)
- Automatic conversion handled by the connector

### Order Book Management
- **Sorting**: Backpack's raw data is automatically sorted (bids descending, asks ascending)
- **Updates**: Incremental updates via WebSocket for real-time accuracy
- **Snapshots**: Periodic snapshots for synchronization

### WebSocket Implementation
- **Stream Format**: `<type>.<symbol>` (e.g., `depth.SOL_USDC`, `trade.BTC_USDC`)
- **Timestamp Handling**: Microseconds converted to seconds internally
- **Reconnection**: Automatic with exponential backoff
- **Health Monitoring**: Connection staleness detection

### Rate Limiting
- Conservative rate limits implemented to prevent API throttling
- Default: 10 requests per second per endpoint
- Automatic request queuing and throttling

## Configuration

### Using with API Credentials (Live Trading)

```python
from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
from hummingbot.client.config.config_helpers import ClientConfigAdapter

# Create exchange instance with API credentials
exchange = BackpackExchange(
    client_config_map=ClientConfigAdapter(ClientConfigMap()),
    api_key="your_public_api_key",
    api_secret="your_base64_encoded_private_key",
    trading_pairs=["SOL-USDC", "BTC-USDC"],
    trading_required=True
)

# The connector will automatically:
# - Fetch trading rules
# - Subscribe to market data
# - Enable order placement and cancellation
```

### Demo Mode (Paper Trading)

```python
# Create exchange instance without API credentials for demo mode
exchange = BackpackExchange(
    client_config_map=ClientConfigAdapter(ClientConfigMap()),
    api_key="",
    api_secret="",
    trading_pairs=["SOL-USDC", "BTC-USDC"],
    demo_mode=True
)

# Demo mode simulates:
# - Order placement and fills
# - Balance updates
# - No real trades executed
```

## Project Structure

### Core Files
- `backpack_exchange.py` - Main exchange connector class implementing trading logic
- `backpack_auth.py` - ED25519 authentication implementation
- `backpack_api_order_book_data_source.py` - WebSocket order book data handling with reconnection logic
- `backpack_constants.py` - Exchange constants, endpoints, and rate limits
- `backpack_utils.py` - Utility functions for data conversion and parsing
- `backpack_web_utils.py` - Web request helpers and API factory

### Test Files
- `test_backpack_auth.py` - Authentication module tests (13 test cases)
- `test_backpack_exchange.py` - Exchange connector tests (14 test cases)
- `test_backpack_api_order_book_data_source.py` - Order book and WebSocket tests (12 test cases)
- `test_backpack_web_utils.py` - Utility function tests (8 test cases)

## Testing

### Running Unit Tests
```bash
# Run all Backpack connector tests
python -m pytest test/hummingbot/connector/exchange/backpack/

# Run specific test file
python -m pytest test/hummingbot/connector/exchange/backpack/test_backpack_exchange.py

# Run with coverage
python -m pytest test/hummingbot/connector/exchange/backpack/ --cov=hummingbot.connector.exchange.backpack
```

### Manual Testing
```bash
# Test public API connectivity
python scripts/test_backpack_public_api.py

# Test with Hummingbot CLI
bin/hummingbot_quickstart.py
>>> connect backpack
>>> balance
>>> order_book SOL-USDC
```

## Troubleshooting

### Common Issues

1. **ModuleNotFoundError: No module named 'nacl'**
   - Solution: Install PyNaCl dependency
   ```bash
   pip install pynacl
   ```

2. **WebSocket Connection Drops**
   - The connector automatically reconnects with exponential backoff
   - Check logs for reconnection attempts and errors
   - Verify network connectivity

3. **Authentication Errors**
   - Ensure API secret is base64 encoded
   - Verify API key has necessary permissions
   - Check system time synchronization

4. **Order Placement Failures**
   - Verify trading pair is active on exchange
   - Check minimum order size and notional requirements
   - Ensure sufficient balance

### Debug Logging

Enable debug logging for detailed connector information:
```python
import logging
logging.getLogger("hummingbot.connector.exchange.backpack").setLevel(logging.DEBUG)
```

## API Documentation

For detailed API documentation, refer to:
- [Backpack Exchange API Documentation](https://docs.backpack.exchange/)
- API specification file: `/api-doc/backpack.json`

## Contributing

When contributing to this connector:
1. Follow existing code patterns and conventions
2. Add unit tests for new functionality
3. Update documentation as needed
4. Ensure all tests pass before submitting PR

## Known Limitations

- Order book depth limited to top 1000 levels
- WebSocket reconnection may briefly interrupt data flow
- Rate limits are conservative (10 req/s) pending official documentation

## Future Enhancements

- [ ] Integration tests with live API endpoints
- [ ] Advanced order types (stop-loss, take-profit)
- [ ] Historical data fetching
- [ ] Account transaction history
- [ ] Consolidated spot/perpetual connector logic