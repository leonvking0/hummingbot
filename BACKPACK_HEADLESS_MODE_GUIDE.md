# Backpack Exchange Headless Mode Guide

This guide explains how to run Hummingbot with Backpack Exchange in headless mode with actual API authentication.

## Prerequisites

1. Backpack Exchange API credentials (API key and secret)
2. Hummingbot installed and compiled
3. Password for Hummingbot (used for encrypting API keys)

## Setup Steps

### 1. Configure API Credentials

First, connect to Backpack Exchange in interactive mode to save your API credentials:

```bash
bin/hummingbot.py
```

In Hummingbot console:
```
connect backpack
```

Enter your API credentials when prompted. They will be encrypted and saved to `conf/connectors/backpack.yml`.

### 2. Create a Trading Script

Create a new script in the `scripts/` directory. Example: `scripts/my_backpack_strategy.py`

```python
import logging
from decimal import Decimal
from typing import Dict, Optional
from pydantic import Field
from hummingbot.client.config.config_data_types import BaseClientModel
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase

class MyBackpackStrategyConfig(BaseClientModel):
    script_file_name: str = "my_backpack_strategy.py"
    exchange: str = Field("backpack")
    trading_pair: str = Field("SOL-USDC")
    # Add your strategy parameters here

class MyBackpackStrategy(ScriptStrategyBase):
    markets = {"backpack": {"SOL-USDC"}}
    
    @classmethod
    def init_markets(cls, config: MyBackpackStrategyConfig):
        cls.markets = {config.exchange: {config.trading_pair}}
    
    def __init__(self, connectors: Dict[str, ConnectorBase], config: Optional[MyBackpackStrategyConfig] = None):
        super().__init__(connectors)
        self.config = config or MyBackpackStrategyConfig()
    
    def on_tick(self):
        # Your trading logic here
        pass
```

### 3. Run in Headless Mode

```bash
bin/hummingbot_quickstart.py -p 'your_password' -f my_backpack_strategy.py --headless
```

Or run with output logging:
```bash
bin/hummingbot_quickstart.py -p 'your_password' -f my_backpack_strategy.py --headless > output.log 2>&1 &
```

## Important Notes

### Spot vs Perpetual Trading

Hummingbot uses separate connectors for spot and perpetual trading:

- **Spot Trading**: Use `backpack` connector (handles spot markets only)
- **Perpetual Trading**: Use `backpack_perpetual` connector (handles PERP markets only)

This separation is by design and follows Hummingbot's standard architecture pattern.

### Authentication Flow

1. API keys are stored encrypted in `conf/connectors/backpack.yml`
2. When running in headless mode, the password decrypts the API keys
3. The connector uses ED25519 signatures for authentication (not HMAC)
4. Balances and order books are fetched automatically once authenticated

### Troubleshooting

If authentication fails:
1. Verify API keys are correctly configured: `connect backpack` in interactive mode
2. Check that your account has funds (balance API returns empty dict for zero balances)
3. Ensure you're using the correct password when running headless mode
4. Check logs for specific error messages

### Example Output

When running successfully, you should see:
```
BackpackExchange - Updated balances: 1 assets
script_strategy_base - Balances: 1 assets
script_strategy_base -   USDC: total=69.9424, available=69.9424
script_strategy_base - Order book for SOL-USDC:
script_strategy_base -   Bid: 180.3500, Ask: 180.3600, Mid: 180.3550
```

## Test Script

A test script is available at `scripts/backpack_auth_test.py` to verify authentication and basic functionality.