# Test Backpack Exchange Trading Functions

## Problem Analysis
- Data fetching works without problem
- Trading functions have issues that are hard to debug in the Hummingbot console
- Need a way to test basic trade functions (place limit order, cancel order) outside the console

## Implementation Plan

### 1. Standalone Test Script ✓
Created `test_backpack_trading.py` that:
- Directly instantiates the Backpack connector without Hummingbot console
- Tests authentication and balance retrieval
- Places a test limit buy order (0.001 SOL at 10% below mid price)
- Cancels the order
- Comprehensive logging to file and console
- Event handlers for all order events

Key features implemented:
- Uses asyncio for proper async handling
- Detailed error logging with stack traces
- Small test amounts (0.001 SOL) to minimize risk
- Environment variable configuration for API keys
- Separate log file for debugging

### 2. Debug Configuration ✓
Created `debug/backpack_debug_config.yml` with:
- Verbose logging settings for all Backpack components
- HTTP request/response logging configuration
- Signature debugging options
- Performance monitoring settings
- Error handling configuration

Created `debug/setup_debug_logging.py` with:
- Debug configuration loader
- HTTP request/response logger
- Signature debug logger
- Helper functions for test configuration

### 3. Authentication Testing ✓
Created `test_backpack_auth.py` that tests:
- ED25519 signature generation according to Backpack API spec
- API key format validation (32-byte public key, 32/64-byte private key)
- Signature verification using NaCl
- Various signing scenarios (orders, cancellations, batch orders, balance queries)
- Key pair relationship verification

### 4. Integration Tests (TODO)
Will create `test_backpack_trading_functions.py` with:
- Real API integration tests
- Error scenario testing
- Edge cases for order placement

## Usage Instructions

### 1. Environment Setup
Set environment variables:
```bash
export BACKPACK_API_KEY='your_base64_public_key'
export BACKPACK_API_SECRET='your_base64_private_key'
```

### 2. Test Authentication
Run the authentication test first to verify your API keys:
```bash
cd /Users/han/github/hummingbot
python test_backpack_auth.py
```

This will verify:
- API key format (proper base64 encoding)
- ED25519 signature generation
- Key pair relationship

### 3. Test Trading Functions
Run the trading test script:
```bash
python test_backpack_trading.py
```

### 4. Check Logs
- Console output for real-time feedback
- `backpack_test.log` for detailed debugging
- `backpack_debug_requests.log` for HTTP request/response logs (if debug config is used)

## Test Flow
1. Initialize exchange connector
2. Test authentication by fetching balances
3. Get current mid price from order book
4. Place limit buy order at 10% below mid price
5. Wait and check order status
6. Cancel the order
7. Verify cancellation

## Deliverables Summary

### Test Scripts Created:
1. **`test_backpack_trading.py`** - Comprehensive trading test that:
   - Tests authentication and balance retrieval
   - Places test limit orders (0.001 SOL)
   - Monitors order status
   - Cancels orders
   - Includes event handlers and detailed logging

2. **`test_backpack_auth.py`** - Authentication test that:
   - Verifies ED25519 signature generation
   - Tests API key format
   - Validates multiple signing scenarios
   - Checks key pair relationships

### Debug Configuration:
1. **`debug/backpack_debug_config.yml`** - Debug settings for:
   - Verbose logging configuration
   - HTTP request/response capture
   - Signature debugging
   - Performance monitoring

2. **`debug/setup_debug_logging.py`** - Helper utilities for:
   - Loading debug configuration
   - HTTP request/response logging
   - Signature debug logging

### Documentation:
1. **`BACKPACK_TROUBLESHOOTING.md`** - Comprehensive guide covering:
   - Common authentication errors
   - Order placement issues
   - Debug techniques
   - Step-by-step debugging process

## Next Steps for Testing

1. **Run Authentication Test First:**
   ```bash
   export BACKPACK_API_KEY='your_key'
   export BACKPACK_API_SECRET='your_secret'
   python test_backpack_auth.py
   ```

2. **Run Trading Test:**
   ```bash
   python test_backpack_trading.py
   ```

3. **Analyze Results:**
   - Check `backpack_test.log` for detailed errors
   - Look for specific error codes (INVALID_SIGNATURE, INVALID_ORDER, etc.)
   - Use the troubleshooting guide to resolve issues

4. **If Issues Persist:**
   - Enable debug configuration
   - Capture HTTP request/response logs
   - Test with even smaller amounts or further price offsets
   - Compare with direct API calls using curl