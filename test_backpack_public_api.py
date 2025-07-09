#!/usr/bin/env python3
"""
Test script for Backpack Exchange public API endpoints
"""

import asyncio
import aiohttp
import json
from typing import Dict, Any


class BackpackPublicAPITester:
    """Test Backpack public API endpoints"""
    
    BASE_URL = "https://api.backpack.exchange"
    
    async def test_markets(self) -> Dict[str, Any]:
        """Test /api/v1/markets endpoint"""
        print("\n=== Testing Markets Endpoint ===")
        url = f"{self.BASE_URL}/api/v1/markets"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                
                print(f"Status: {response.status}")
                print(f"Number of markets: {len(data)}")
                
                # Show first 3 markets
                for i, market in enumerate(data[:3]):
                    print(f"\nMarket {i+1}:")
                    print(f"  Symbol: {market.get('symbol')}")
                    print(f"  Status: {market.get('status')}")
                    print(f"  Type: {market.get('marketType')}")
                    
                return {"status": response.status, "count": len(data), "sample": data[:3]}
    
    async def test_depth(self, symbol: str = "SOL_USDC") -> Dict[str, Any]:
        """Test /api/v1/depth endpoint"""
        print(f"\n=== Testing Depth Endpoint for {symbol} ===")
        url = f"{self.BASE_URL}/api/v1/depth"
        params = {"symbol": symbol}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                data = await response.json()
                
                print(f"Status: {response.status}")
                
                if response.status == 200:
                    bids = data.get("bids", [])
                    asks = data.get("asks", [])
                    
                    print(f"Number of bids: {len(bids)}")
                    print(f"Number of asks: {len(asks)}")
                    
                    # Debug: Show raw format and check sorting
                    if bids:
                        print(f"\nTop 5 bids:")
                        for i in range(min(5, len(bids))):
                            print(f"  {i+1}. Price={bids[i][0]}, Quantity={bids[i][1]}")
                        # Find highest bid
                        highest_bid = max(bids, key=lambda x: float(x[0]))
                        print(f"Highest bid: Price={highest_bid[0]}, Quantity={highest_bid[1]}")
                        
                    if asks:
                        print(f"\nTop 5 asks:")
                        for i in range(min(5, len(asks))):
                            print(f"  {i+1}. Price={asks[i][0]}, Quantity={asks[i][1]}")
                        # Find lowest ask
                        lowest_ask = min(asks, key=lambda x: float(x[0]))
                        print(f"Lowest ask: Price={lowest_ask[0]}, Quantity={lowest_ask[1]}")
                    
                    # Calculate spread (using highest bid and lowest ask)
                    if bids and asks:
                        # Use the highest bid and lowest ask for proper spread calculation
                        best_bid_price = float(highest_bid[0]) if 'highest_bid' in locals() else max(float(b[0]) for b in bids)
                        best_ask_price = float(lowest_ask[0]) if 'lowest_ask' in locals() else min(float(a[0]) for a in asks)
                        spread = best_ask_price - best_bid_price
                        mid_price = (best_ask_price + best_bid_price) / 2
                        spread_pct = (spread / mid_price) * 100
                        print(f"\nProper spread calculation:")
                        print(f"Best bid: {best_bid_price:.2f}")
                        print(f"Best ask: {best_ask_price:.2f}")
                        print(f"Spread: {spread:.4f} ({spread_pct:.2f}%)")
                        
                return {"status": response.status, "data": data}
    
    async def test_ticker(self, symbol: str = "SOL_USDC") -> Dict[str, Any]:
        """Test /api/v1/ticker endpoint"""
        print(f"\n=== Testing Ticker Endpoint for {symbol} ===")
        url = f"{self.BASE_URL}/api/v1/ticker"
        params = {"symbol": symbol}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                data = await response.json()
                
                print(f"Status: {response.status}")
                
                if response.status == 200:
                    print(f"Symbol: {data.get('symbol')}")
                    print(f"Last Price: {data.get('lastPrice')}")
                    print(f"24h Change: {data.get('priceChange')} ({data.get('priceChangePercent')}%)")
                    print(f"24h High: {data.get('high')}")
                    print(f"24h Low: {data.get('low')}")
                    print(f"24h Volume: {data.get('volume')}")
                    print(f"Quote Volume: {data.get('quoteVolume')}")
                    
                return {"status": response.status, "data": data}
    
    async def test_tickers(self) -> Dict[str, Any]:
        """Test /api/v1/tickers endpoint"""
        print("\n=== Testing All Tickers Endpoint ===")
        url = f"{self.BASE_URL}/api/v1/tickers"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                
                print(f"Status: {response.status}")
                print(f"Number of tickers: {len(data)}")
                
                # Show top 5 by volume
                sorted_by_volume = sorted(data, key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)
                
                print("\nTop 5 by 24h Quote Volume:")
                for i, ticker in enumerate(sorted_by_volume[:5]):
                    print(f"{i+1}. {ticker.get('symbol')}: ${float(ticker.get('quoteVolume', 0)):,.2f}")
                    
                return {"status": response.status, "count": len(data)}
    
    async def test_trades(self, symbol: str = "SOL_USDC") -> Dict[str, Any]:
        """Test /api/v1/trades endpoint"""
        print(f"\n=== Testing Trades Endpoint for {symbol} ===")
        url = f"{self.BASE_URL}/api/v1/trades"
        params = {"symbol": symbol}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                data = await response.json()
                
                print(f"Status: {response.status}")
                
                if response.status == 200:
                    print(f"Number of trades: {len(data)}")
                    
                    # Show last 5 trades
                    for i, trade in enumerate(data[:5]):
                        side = "BUY" if trade.get("isBuyerMaker") else "SELL"
                        print(f"Trade {i+1}: {side} {trade.get('quantity')} @ {trade.get('price')}")
                        
                return {"status": response.status, "count": len(data)}
    
    async def test_websocket_connection(self):
        """Test WebSocket connection"""
        print("\n=== Testing WebSocket Connection ===")
        ws_url = "wss://ws.backpack.exchange"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(ws_url) as ws:
                    print("WebSocket connected successfully!")
                    
                    # Subscribe to depth stream for SOL_USDC
                    subscribe_msg = {
                        "method": "SUBSCRIBE",
                        "params": ["depth.SOL_USDC"]
                    }
                    
                    await ws.send_json(subscribe_msg)
                    print("Subscription message sent")
                    
                    # Listen for a few messages
                    msg_count = 0
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            if "stream" in data:
                                msg_count += 1
                                print(f"Received message {msg_count} from stream: {data.get('stream')}")
                                
                                if msg_count >= 3:
                                    break
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            print(f"WebSocket error: {ws.exception()}")
                            break
                            
                    await ws.close()
                    
        except Exception as e:
            print(f"WebSocket connection error: {str(e)}")
    
    async def run_all_tests(self):
        """Run all tests"""
        print("Starting Backpack Exchange Public API Tests...")
        
        results = {}
        
        # Test each endpoint
        try:
            results["markets"] = await self.test_markets()
        except Exception as e:
            print(f"Markets test failed: {str(e)}")
            results["markets"] = {"error": str(e)}
        
        try:
            results["depth"] = await self.test_depth()
        except Exception as e:
            print(f"Depth test failed: {str(e)}")
            results["depth"] = {"error": str(e)}
        
        try:
            results["ticker"] = await self.test_ticker()
        except Exception as e:
            print(f"Ticker test failed: {str(e)}")
            results["ticker"] = {"error": str(e)}
        
        try:
            results["tickers"] = await self.test_tickers()
        except Exception as e:
            print(f"Tickers test failed: {str(e)}")
            results["tickers"] = {"error": str(e)}
        
        try:
            results["trades"] = await self.test_trades()
        except Exception as e:
            print(f"Trades test failed: {str(e)}")
            results["trades"] = {"error": str(e)}
        
        try:
            await self.test_websocket_connection()
            results["websocket"] = {"status": "connected"}
        except Exception as e:
            print(f"WebSocket test failed: {str(e)}")
            results["websocket"] = {"error": str(e)}
        
        print("\n=== Test Summary ===")
        for endpoint, result in results.items():
            if "error" in result:
                print(f"{endpoint}: FAILED - {result['error']}")
            else:
                print(f"{endpoint}: SUCCESS")
        
        return results


async def main():
    """Main function"""
    tester = BackpackPublicAPITester()
    await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())