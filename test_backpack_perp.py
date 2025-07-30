#!/usr/bin/env python3
"""
Test script for Backpack Exchange Perpetual trading
Tests SOL_USDC_PERP trading pair functionality
"""

import asyncio
import base64
import logging
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlencode

# Try to load from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value

# Add hummingbot to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import aiohttp
from nacl.signing import SigningKey
from hummingbot.connector.exchange.backpack.backpack_auth import BackpackAuth
from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


class BackpackPerpTest:
    """Test Backpack Exchange Perpetual trading"""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.auth = BackpackAuth(api_key, api_secret)
        self.base_url = "https://api.backpack.exchange"
        self.session: Optional[aiohttp.ClientSession] = None
        self.perp_symbol = "SOL_USDC_PERP"
        self.spot_symbol = "SOL_USDC"
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def _request(self, method: str, endpoint: str, params: Dict = None, auth_required: bool = False):
        """Make a request to the Backpack API"""
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "hummingbot"
        }
        
        if auth_required:
            timestamp = int(time.time() * 1000)
            window = 5000
            
            # Determine instruction based on endpoint
            instruction = self._get_instruction(method, endpoint)
            
            # Generate auth string and signature
            auth_string = self.auth.generate_auth_string(instruction, params, timestamp, window)
            signature = self.auth.get_signature(auth_string)
            
            # Add auth headers
            headers.update({
                "X-API-Key": self.api_key,
                "X-Signature": signature,
                "X-Timestamp": str(timestamp),
                "X-Window": str(window)
            })
            
            logger.debug(f"Auth headers added for {instruction}")
            logger.debug(f"Auth string: {auth_string}")
        
        logger.info(f"{method} {url}")
        if params:
            logger.debug(f"Params: {params}")
        
        try:
            if method == "GET":
                async with self.session.get(url, params=params, headers=headers) as response:
                    return await self._handle_response(response)
            elif method == "POST":
                async with self.session.post(url, json=params, headers=headers) as response:
                    return await self._handle_response(response)
            elif method == "DELETE":
                async with self.session.delete(url, json=params, headers=headers) as response:
                    return await self._handle_response(response)
        except Exception as e:
            logger.error(f"Request failed: {e}", exc_info=True)
            raise
    
    async def _handle_response(self, response):
        """Handle API response"""
        text = await response.text()
        logger.debug(f"Response status: {response.status}")
        logger.debug(f"Response text: {text[:500]}...")  # First 500 chars
        
        if response.status >= 400:
            logger.error(f"API error: {response.status} - {text}")
            raise Exception(f"API error: {response.status} - {text}")
        
        try:
            import json
            return json.loads(text) if text else None
        except json.JSONDecodeError:
            return text
    
    def _get_instruction(self, method: str, endpoint: str) -> str:
        """Get instruction type for endpoint"""
        if "/capital" in endpoint:
            if method == "GET":
                return "balanceQuery"
        elif "/positions" in endpoint:
            return "positionQuery"
        elif "/orders" in endpoint:
            if method == "POST":
                return "orderExecute"
            elif method == "DELETE":
                return "orderCancelAll"
            elif method == "GET":
                return "orderQueryAll"
        elif "/order" in endpoint:
            if method == "POST":
                return "orderExecute"
            elif method == "DELETE":
                return "orderCancel"
            elif method == "GET":
                return "orderQuery"
        elif "/collateral" in endpoint:
            return "collateralQuery"
        return "accountQuery"
    
    async def test_perp_market_info(self):
        """Test perpetual market information"""
        logger.info("\n=== Testing Perpetual Market Info ===")
        
        # Get all markets
        markets = await self._request("GET", "/api/v1/markets")
        
        # Find perpetual markets
        perp_markets = [m for m in markets if m['symbol'].endswith('_PERP')]
        logger.info(f"Found {len(perp_markets)} perpetual markets")
        
        # Find SOL_USDC_PERP
        sol_perp = next((m for m in markets if m['symbol'] == self.perp_symbol), None)
        if sol_perp:
            logger.info(f"\n{self.perp_symbol} market info:")
            logger.info(f"  Base Symbol: {sol_perp.get('baseSymbol')}")
            logger.info(f"  Quote Symbol: {sol_perp.get('quoteSymbol')}")
            logger.info(f"  Market Type: {sol_perp.get('marketType', 'N/A')}")
            logger.info(f"  Filters: {sol_perp.get('filters')}")
            
            # Check specific perp fields
            logger.info(f"  Funding Interval: {sol_perp.get('fundingInterval')} ms")
            logger.info(f"  Max Leverage: {sol_perp.get('maxLeverage', 'N/A')}")
            logger.info(f"  Initial Margin Rate: {sol_perp.get('initialMarginRate', 'N/A')}")
            logger.info(f"  Maintenance Margin Rate: {sol_perp.get('maintenanceMarginRate', 'N/A')}")
            
            return sol_perp
        else:
            logger.error(f"{self.perp_symbol} market not found!")
            return None
    
    async def test_perp_ticker(self):
        """Test perpetual ticker data"""
        logger.info(f"\n=== Testing {self.perp_symbol} Ticker ===")
        
        ticker = await self._request("GET", "/api/v1/ticker", {"symbol": self.perp_symbol})
        logger.info(f"{self.perp_symbol} ticker:")
        logger.info(f"  Last price: {ticker.get('lastPrice')}")
        logger.info(f"  24h High: {ticker.get('high')} / Low: {ticker.get('low')}")
        logger.info(f"  24h Volume: {ticker.get('volume')}")
        logger.info(f"  24h Quote Volume: {ticker.get('quoteVolume')}")
        logger.info(f"  Price Change: {ticker.get('priceChange')} ({ticker.get('priceChangePercent')}%)")
        
        return ticker
    
    async def test_perp_orderbook(self):
        """Test perpetual order book"""
        logger.info(f"\n=== Testing {self.perp_symbol} Order Book ===")
        
        depth = await self._request("GET", "/api/v1/depth", {"symbol": self.perp_symbol})
        logger.info(f"{self.perp_symbol} order book:")
        logger.info(f"  Bids: {len(depth.get('bids', []))} levels")
        logger.info(f"  Asks: {len(depth.get('asks', []))} levels")
        
        if depth.get('bids') and len(depth['bids']) > 0:
            logger.info(f"  Best bid: Price={depth['bids'][0][0]}, Size={depth['bids'][0][1]}")
        if depth.get('asks') and len(depth['asks']) > 0:
            logger.info(f"  Best ask: Price={depth['asks'][0][0]}, Size={depth['asks'][0][1]}")
            
        return depth
    
    async def test_account_info(self):
        """Test account information for perpetuals"""
        logger.info("\n=== Testing Account Info for Perpetuals ===")
        
        # Get balances
        logger.info("\n1. Account Balances:")
        try:
            balances = await self._request("GET", "/api/v1/capital", auth_required=True)
            for symbol, balance_info in balances.items():
                if balance_info.get('available') != '0' or symbol == 'USDC':
                    logger.info(f"  {symbol}: Available={balance_info.get('available')}, "
                              f"Locked={balance_info.get('locked')}, Staked={balance_info.get('staked')}")
        except Exception as e:
            logger.error(f"Failed to get balances: {e}")
        
        # Get positions
        logger.info("\n2. Perpetual Positions:")
        try:
            positions = await self._request("GET", "/api/v1/positions", auth_required=True)
            if isinstance(positions, list) and len(positions) > 0:
                for pos in positions:
                    logger.info(f"  Symbol: {pos.get('symbol')}")
                    logger.info(f"    Side: {pos.get('side')}")
                    logger.info(f"    Size: {pos.get('size')}")
                    logger.info(f"    Entry Price: {pos.get('entryPrice')}")
                    logger.info(f"    Mark Price: {pos.get('markPrice')}")
                    logger.info(f"    PnL: {pos.get('pnl')}")
            else:
                logger.info("  No open positions")
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
        
        # Get collateral info
        logger.info("\n3. Collateral Info:")
        try:
            collateral = await self._request("GET", "/api/v1/collateral", auth_required=True)
            if isinstance(collateral, list):
                logger.info("  Collateral configuration by asset:")
                for asset in collateral:
                    if asset.get('symbol') in ['USDC', 'USDT', 'SOL']:
                        logger.info(f"    {asset.get('symbol')}: IMF={asset.get('imfFunction', {}).get('base', 'N/A')}, "
                                  f"MMF={asset.get('mmfFunction', {}).get('base', 'N/A')}")
            else:
                logger.info(f"  Collateral data: {collateral}")
        except Exception as e:
            logger.error(f"Failed to get collateral info: {e}")
    
    async def test_perp_order_placement(self):
        """Test perpetual order placement"""
        logger.info(f"\n=== Testing {self.perp_symbol} Order Placement ===")
        
        # Get current price
        ticker = await self._request("GET", "/api/v1/ticker", {"symbol": self.perp_symbol})
        last_price = Decimal(ticker.get('lastPrice', '0'))
        
        if last_price == 0:
            logger.error("Could not get current price")
            return None
        
        # Get market info for minimum quantities
        markets = await self._request("GET", "/api/v1/markets")
        sol_perp = next((m for m in markets if m['symbol'] == self.perp_symbol), None)
        
        if not sol_perp:
            logger.error(f"Could not find {self.perp_symbol} market info")
            return None
        
        # Extract minimum quantity
        min_qty = Decimal(sol_perp['filters']['quantity']['minQuantity'])
        tick_size = Decimal(sol_perp['filters']['price']['tickSize'])
        
        logger.info(f"Market constraints:")
        logger.info(f"  Min quantity: {min_qty}")
        logger.info(f"  Tick size: {tick_size}")
        logger.info(f"  Current price: {last_price}")
        
        # Place a buy order 20% below market
        buy_price = last_price * Decimal('0.8')
        # Round to tick size
        buy_price = (buy_price / tick_size).quantize(Decimal('1')) * tick_size
        
        order_params = {
            "symbol": self.perp_symbol,
            "side": "Bid",
            "orderType": "Limit",
            "price": str(buy_price),
            "quantity": str(min_qty),  # Use minimum allowed
            "timeInForce": "GTC"
            # Note: postOnly parameter might need special handling
        }
        
        logger.info(f"Placing test order: Buy {min_qty} SOL perp @ ${buy_price}")
        
        try:
            response = await self._request("POST", "/api/v1/order", 
                                         params=order_params, 
                                         auth_required=True)
            
            if response and 'id' in response:
                order_id = response['id']
                logger.info(f"✅ Perpetual order placed successfully!")
                logger.info(f"  Order ID: {order_id}")
                logger.info(f"  Status: {response.get('status')}")
                logger.info(f"  Order details: {response}")
                return order_id
            else:
                logger.error(f"Unexpected order response: {response}")
                return None
                
        except Exception as e:
            logger.error(f"Perpetual order placement failed: {e}")
            return None
    
    async def test_perp_order_query(self, order_id: str):
        """Query a specific perpetual order"""
        logger.info(f"\n=== Querying Perpetual Order {order_id} ===")
        
        try:
            # Query single order
            order = await self._request("GET", f"/api/v1/order", 
                                      params={"orderId": order_id, "symbol": self.perp_symbol},
                                      auth_required=True)
            
            logger.info(f"Order details:")
            logger.info(f"  ID: {order.get('id')}")
            logger.info(f"  Symbol: {order.get('symbol')}")
            logger.info(f"  Status: {order.get('status')}")
            logger.info(f"  Price: {order.get('price')}")
            logger.info(f"  Quantity: {order.get('quantity')}")
            logger.info(f"  Executed: {order.get('executedQuantity')}")
            
            # Also check open orders
            open_orders = await self._request("GET", "/api/v1/orders",
                                            params={"symbol": self.perp_symbol},
                                            auth_required=True)
            
            logger.info(f"\nOpen {self.perp_symbol} orders: {len(open_orders) if isinstance(open_orders, list) else 0}")
            
            return order
            
        except Exception as e:
            logger.error(f"Order query failed: {e}")
            return None
    
    async def test_perp_order_cancellation(self, order_id: str):
        """Test perpetual order cancellation"""
        logger.info(f"\n=== Testing Perpetual Order Cancellation ===")
        logger.info(f"Cancelling order ID: {order_id}")
        
        cancel_params = {
            "symbol": self.perp_symbol,
            "orderId": order_id
        }
        
        try:
            response = await self._request("DELETE", "/api/v1/order", 
                                         params=cancel_params, 
                                         auth_required=True)
            
            logger.info(f"✅ Cancel successful!")
            logger.info(f"  Final status: {response.get('status')}")
            logger.info(f"  Response: {response}")
            return True
            
        except Exception as e:
            logger.error(f"Perpetual order cancellation failed: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all perpetual trading tests"""
        logger.info("=" * 60)
        logger.info("Starting Backpack Exchange PERPETUAL tests")
        logger.info("=" * 60)
        
        # Test market info
        market_info = await self.test_perp_market_info()
        if not market_info:
            logger.error("Could not get perpetual market info, aborting tests")
            return
        
        # Test ticker
        await self.test_perp_ticker()
        
        # Test order book
        await self.test_perp_orderbook()
        
        # Test account info
        await self.test_account_info()
        
        # Test order placement
        order_id = await self.test_perp_order_placement()
        
        if order_id:
            # Wait a bit
            logger.info("\nWaiting 3 seconds...")
            await asyncio.sleep(3)
            
            # Query the order
            await self.test_perp_order_query(str(order_id))
            
            # Cancel the order
            await self.test_perp_order_cancellation(str(order_id))
        
        logger.info("\n" + "=" * 60)
        logger.info("All perpetual tests completed!")
        logger.info("=" * 60)


async def main():
    """Main entry point"""
    api_key = os.getenv("BACKPACK_API_KEY")
    api_secret = os.getenv("BACKPACK_API_SECRET")
    
    if not api_key or not api_secret:
        logger.error("Please set BACKPACK_API_KEY and BACKPACK_API_SECRET")
        return
    
    async with BackpackPerpTest(api_key, api_secret) as tester:
        await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())