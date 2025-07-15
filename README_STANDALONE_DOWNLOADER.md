# Standalone Order Book and Trades Downloader

This script allows you to download order book snapshots and trade history data without entering the Hummingbot console.

## Usage

1. Activate the Hummingbot conda environment:
```bash
conda activate hummingbot
```

2. Run the script:
```bash
python download_orderbook_trades_standalone.py
```

## Configuration

You can configure the script using environment variables:

- `EXCHANGE`: Exchange to download data from (default: "binance_paper_trade")
  - Supported: "binance", "binance_paper_trade", "backpack"
- `TRADING_PAIRS`: Comma-separated list of trading pairs (default: "ETH-USDT,BTC-USDT")
- `DEPTH`: Order book depth to capture (default: 50)
- `DUMP_INTERVAL`: Interval in seconds between data dumps to file (default: 10)

### Examples

```bash
# Download BTC-USDT data from Binance
EXCHANGE=binance TRADING_PAIRS=BTC-USDT python download_orderbook_trades_standalone.py

# Download multiple pairs from Binance paper trade
EXCHANGE=binance_paper_trade TRADING_PAIRS="ETH-USDT,BTC-USDT,SOL-USDT" python download_orderbook_trades_standalone.py

# Download with custom depth and interval
EXCHANGE=binance TRADING_PAIRS=BTC-USDT DEPTH=100 DUMP_INTERVAL=5 python download_orderbook_trades_standalone.py
```

## Output

Data files are saved to the `data/` directory with the following naming format:
- Order book snapshots: `{exchange}_{trading_pair}_order_book_snapshots_{date}.txt`
- Trades: `{exchange}_{trading_pair}_trades_{date}.txt`

Each line in the files contains a JSON object with the following structure:

### Order Book Snapshot
```json
{
  "ts": 1752608317.0,
  "bids": [[price, amount], ...],
  "asks": [[price, amount], ...]
}
```

### Trade
```json
{
  "ts": 1752608314.944,
  "price": 116519.97,
  "q_base": 0.001,
  "side": "buy"
}
```

## Notes

- The script automatically handles date changes and creates new files for each day
- Data is buffered and written to disk every `DUMP_INTERVAL` seconds
- Press Ctrl+C to stop the script gracefully
- For authenticated exchanges, set the appropriate API key environment variables:
  - Binance: `BINANCE_API_KEY` and `BINANCE_API_SECRET`
  - Backpack: `BACKPACK_API_KEY` and `BACKPACK_API_SECRET`