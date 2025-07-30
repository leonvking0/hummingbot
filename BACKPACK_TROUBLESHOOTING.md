# Backpack Exchange Troubleshooting Guide

This guide helps diagnose and fix common issues with the Backpack Exchange connector.

## Quick Start

1. **Test authentication first:**
   ```bash
   export BACKPACK_API_KEY='your_base64_public_key'
   export BACKPACK_API_SECRET='your_base64_private_key'
   python test_backpack_auth.py
   ```

2. **Run trading test:**
   ```bash
   python test_backpack_trading.py
   ```

## Common Issues

### 1. Authentication Errors

#### INVALID_SIGNATURE Error
**Symptoms:** 
- API returns "INVALID_SIGNATURE" error
- Orders fail to place with authentication errors

**Solutions:**
1. Verify your API keys are properly base64 encoded:
   ```bash
   python test_backpack_auth.py
   ```

2. Check that you're using ED25519 keys (not HMAC or other types)

3. Ensure the signature generation follows Backpack's exact format:
   - Parameters must be alphabetically sorted
   - Instruction must be prefixed
   - Timestamp and window must be appended

#### Key Format Issues
**Symptoms:**
- "Invalid key format" errors
- Base64 decoding failures

**Solutions:**
1. Public key must be exactly 32 bytes when decoded
2. Private key must be 32 or 64 bytes when decoded
3. Keys must be valid base64 strings (no spaces or newlines)

### 2. Order Placement Failures

#### Client Order ID Issues
**Symptoms:**
- Orders rejected due to invalid client ID
- "Client ID must be uint32" errors

**Solutions:**
1. Backpack uses uint32 for client order IDs (max value: 4294967295)
2. The connector tries to extract numeric parts from Hummingbot's order IDs
3. If extraction fails, client ID is omitted (which is allowed)

#### Symbol Format Issues
**Symptoms:**
- "Invalid symbol" errors
- Orders rejected immediately

**Solutions:**
1. Backpack uses underscores in symbols: `SOL_USDC` not `SOL-USDC`
2. The connector automatically converts formats
3. Verify symbol exists on Backpack: check `/api/v1/markets`

### 3. Connection Issues

#### WebSocket Disconnections
**Symptoms:**
- Order book stops updating
- "WebSocket disconnected" messages

**Solutions:**
1. Check network connectivity
2. Verify WebSocket endpoint: `wss://ws.backpack.exchange/`
3. Enable debug logging to see reconnection attempts

#### Rate Limiting
**Symptoms:**
- "RATE_LIMIT_EXCEEDED" errors
- Requests timing out

**Solutions:**
1. The connector implements rate limiting
2. Default limits are conservative
3. If still hitting limits, reduce order frequency

## Debug Tools

### 1. Enable Verbose Logging

Create a file `debug_backpack.py`:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("hummingbot.connector.exchange.backpack").setLevel(logging.DEBUG)

# Then run your normal Hummingbot commands
```

### 2. Test Specific Functions

Test order placement directly:
```python
# In test_backpack_trading.py, modify test_order_placement() to:
# - Use even smaller amounts (0.0001 SOL)
# - Place orders further from mid price (20% offset)
# - Add more logging around each step
```

### 3. Capture HTTP Traffic

Modify `backpack_web_utils.py` to log all requests:
```python
# Add to create_rest_assistant():
import json
logger.debug(f"Request: {method} {url}")
logger.debug(f"Headers: {headers}")
logger.debug(f"Body: {json.dumps(data) if data else 'None'}")
```

## Step-by-Step Debugging Process

1. **Verify API Keys:**
   ```bash
   python test_backpack_auth.py
   ```
   - Should show "✓ All authentication tests passed!"

2. **Test Basic Connectivity:**
   ```python
   # Run a simple balance check
   import asyncio
   from test_backpack_trading import BackpackTradingTest
   
   async def test():
       tester = BackpackTradingTest(api_key, api_secret)
       await tester.initialize()
       await tester.test_authentication()
   
   asyncio.run(test())
   ```

3. **Test Order Placement:**
   - Start with tiny amounts (0.0001 SOL)
   - Use limit orders far from market price
   - Monitor logs for specific error messages

4. **Check Error Responses:**
   - Look for error codes in responses
   - Common codes:
     - `INVALID_SIGNATURE`: Authentication issue
     - `INVALID_ORDER`: Order parameters invalid
     - `INSUFFICIENT_BALANCE`: Not enough funds
     - `RESOURCE_NOT_FOUND`: Order ID doesn't exist

## Getting Help

1. **Check Logs:**
   - `backpack_test.log`: Main test output
   - `logs/`: Hummingbot logs directory
   - Enable debug mode for detailed traces

2. **API Documentation:**
   - Full spec in `/api-doc/backpack.json`
   - Key sections: Authentication, Order Management

3. **Test Scripts:**
   - `test_backpack_auth.py`: Test authentication
   - `test_backpack_trading.py`: Test trading functions
   - `scripts/backpack_simple_buy.py`: Example strategy

## Next Steps

If issues persist after following this guide:

1. Run tests with maximum debug logging
2. Capture the full error messages and stack traces
3. Check if the issue occurs in the Hummingbot console vs standalone scripts
4. Verify the same operations work via Backpack's web interface
5. Consider testing with Backpack's API directly (curl/Postman) to isolate issues