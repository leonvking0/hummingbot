# Backpack Simple Buy Trading Algorithm

This is a simple trading algorithm for Backpack exchange that places buy orders 10% below the current mid price and cancels them every minute if unfilled.

## Important: Fixed in Latest Version
The initial version had a bug with the `markets` attribute. This has been fixed by:
1. Adding `markets = {}` as a class attribute
2. Updating the parent class constructor call to include config
3. Fixing type hints for Python 3.8+ compatibility

## Features

- Places a limit buy order for 0.1 SOL at 10% below mid price
- Automatically cancels and replaces the order every 60 seconds if unfilled
- Logs order placement and fills
- Budget checking to ensure sufficient balance

## Prerequisites

1. Hummingbot installed and configured
2. Backpack API keys configured (use `connect backpack` command)
3. Sufficient USDC balance in your Backpack account

## Configuration

The strategy uses the following default configuration:

- **Exchange**: backpack
- **Trading Pair**: SOL-USDC
- **Order Amount**: 0.1 SOL
- **Price Discount**: 10% below mid price
- **Order Refresh Time**: 60 seconds

You can modify these settings in `conf/scripts/backpack_simple_buy_config.yml`

## Running the Strategy

1. Activate the hummingbot conda environment:
   ```bash
   conda activate hummingbot
   ```

2. Start Hummingbot:
   ```bash
   bin/hummingbot_quickstart.py
   ```

3. Connect your Backpack account (if not already done):
   ```
   connect backpack
   ```
   Enter your API key and secret when prompted.

4. Start the trading algorithm:
   ```
   start --script backpack_simple_buy.py
   ```

## Monitoring

The strategy will log:
- Order placement with price details
- Order cancellations
- Order fills
- Any errors encountered

## Customization

To modify the strategy behavior, edit `scripts/backpack_simple_buy.py`:

- Change `price_discount` to adjust how far below mid price to place orders
- Change `order_amount` to trade different amounts
- Change `order_refresh_time` to cancel/replace orders more or less frequently

## Risk Warning

This is a simple example strategy for educational purposes. Always test with small amounts first and understand the risks involved in automated trading.