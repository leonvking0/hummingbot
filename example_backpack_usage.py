#!/usr/bin/env python3
"""
Example usage of Backpack Exchange connector for Hummingbot
This demonstrates how to use the public API endpoints
"""

import asyncio
import sys
import os
from decimal import Decimal

# Add the hummingbot directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
from hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source import BackpackAPIOrderBookDataSource
from hummingbot.connector.exchange.backpack import backpack_web_utils as web_utils
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler


async def main():
    """
    Example of using Backpack Exchange connector
    """
    print("=== Backpack Exchange Connector Example ===\n")
    
    # Trading pairs to track
    trading_pairs = ["SOL-USDC", "BTC-USDC", "ETH-USDC"]
    
    # Create exchange instance (no API keys needed for public data)
    exchange = BackpackExchange(
        api_key="",
        api_secret="",
        trading_pairs=trading_pairs,
        trading_required=False
    )
    
    # Initialize the exchange
    print("Initializing exchange connector...")
    await exchange._update_trading_rules()
    
    # 1. Display available trading pairs
    print("\n1. Available Trading Pairs:")
    for trading_pair, trading_rule in exchange.trading_rules.items():
        if trading_pair in trading_pairs:
            print(f"\n{trading_pair}:")
            print(f"  Min order size: {trading_rule.min_order_size}")
            print(f"  Max order size: {trading_rule.max_order_size}")
            print(f"  Price increment: {trading_rule.min_price_increment}")
            print(f"  Quantity increment: {trading_rule.min_base_amount_increment}")
    
    # 2. Get last traded prices
    print("\n2. Last Traded Prices:")
    throttler = AsyncThrottler(exchange.rate_limits_rules)
    api_factory = web_utils.build_api_factory(throttler=throttler)
    
    data_source = BackpackAPIOrderBookDataSource(
        trading_pairs=trading_pairs,
        throttler=throttler,
        api_factory=api_factory
    )
    
    last_prices = await data_source.get_last_traded_prices(trading_pairs)
    for pair, price in last_prices.items():
        print(f"  {pair}: ${price:.2f}")
    
    # 3. Get order book snapshots
    print("\n3. Order Book Snapshots:")
    for trading_pair in trading_pairs[:2]:  # Just show first 2
        print(f"\n{trading_pair}:")
        try:
            # Get order book data
            order_book_data = await data_source.get_order_book_data(trading_pair)
            
            # Show top 5 bids and asks
            bids = order_book_data.get("bids", [])
            asks = order_book_data.get("asks", [])
            
            # Sort properly
            sorted_bids = sorted(bids, key=lambda x: float(x[0]), reverse=True)[:5]
            sorted_asks = sorted(asks, key=lambda x: float(x[0]))[:5]
            
            print("  Top 5 Bids:")
            for i, bid in enumerate(sorted_bids):
                print(f"    {i+1}. ${float(bid[0]):.2f} x {float(bid[1]):.2f}")
            
            print("  Top 5 Asks:")
            for i, ask in enumerate(sorted_asks):
                print(f"    {i+1}. ${float(ask[0]):.2f} x {float(ask[1]):.2f}")
            
            # Calculate spread
            if sorted_bids and sorted_asks:
                best_bid = float(sorted_bids[0][0])
                best_ask = float(sorted_asks[0][0])
                spread = best_ask - best_bid
                spread_pct = (spread / ((best_bid + best_ask) / 2)) * 100
                print(f"  Spread: ${spread:.4f} ({spread_pct:.3f}%)")
                
        except Exception as e:
            print(f"  Error fetching order book: {str(e)}")
    
    # 4. Demo WebSocket streaming (run for a few seconds)
    print("\n4. WebSocket Streaming Demo (5 seconds):")
    print("Starting order book streaming...")
    
    # Create queue for order book updates
    order_book_queue = asyncio.Queue()
    
    # Start listening for order book diffs
    listen_task = asyncio.create_task(
        data_source.listen_for_order_book_diffs(
            ev_loop=asyncio.get_event_loop(),
            output=order_book_queue
        )
    )
    
    # Collect updates for 5 seconds
    start_time = asyncio.get_event_loop().time()
    update_count = 0
    
    try:
        while asyncio.get_event_loop().time() - start_time < 5:
            try:
                # Wait for update with timeout
                update = await asyncio.wait_for(order_book_queue.get(), timeout=0.1)
                update_count += 1
                
                # Show first few updates
                if update_count <= 3:
                    print(f"  Update {update_count}: {update.trading_pair} - "
                          f"{len(update.bids)} bid updates, {len(update.asks)} ask updates")
                          
            except asyncio.TimeoutError:
                continue
                
    except Exception as e:
        print(f"  Streaming error: {str(e)}")
    finally:
        # Cancel the listening task
        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass
    
    print(f"  Total updates received: {update_count}")
    
    print("\n=== Example Complete ===")


if __name__ == "__main__":
    asyncio.run(main())