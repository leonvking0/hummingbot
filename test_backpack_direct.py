#!/usr/bin/env python3
"""
Direct API test for Backpack Exchange
Tests API calls directly without full Hummingbot infrastructure
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


class BackpackDirectTest:
    """Direct API testing for Backpack Exchange"""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.auth = BackpackAuth(api_key, api_secret)
        self.base_url = "https://api.backpack.exchange"
        self.session: Optional[aiohttp.ClientSession] = None
        
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
            elif method == "DELETE":
                return "withdraw"
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
        return "accountQuery"
    
    async def test_public_endpoints(self):
        """Test public endpoints"""
        logger.info("\n=== Testing Public Endpoints ===")
        
        # Test markets endpoint
        logger.info("\n1. Testing /api/v1/markets")
        markets = await self._request("GET", "/api/v1/markets")
        logger.info(f"Found {len(markets)} markets")
        
        # Find SOL_USDC market
        sol_usdc = next((m for m in markets if m['symbol'] == 'SOL_USDC'), None)
        if sol_usdc:
            logger.info(f"SOL_USDC market info:")
            logger.info(f"  Status: {sol_usdc.get('status')}")
            logger.info(f"  Filters: {sol_usdc.get('filters')}")
        
        # Test ticker endpoint
        logger.info("\n2. Testing /api/v1/ticker")
        ticker = await self._request("GET", "/api/v1/ticker", {"symbol": "SOL_USDC"})
        logger.info(f"SOL_USDC ticker:")
        logger.info(f"  Last price: {ticker.get('lastPrice')}")
        logger.info(f"  Bid: {ticker.get('bid')} / Ask: {ticker.get('ask')}")
        logger.info(f"  Volume: {ticker.get('volume')}")
        
        # Test depth endpoint
        logger.info("\n3. Testing /api/v1/depth")
        depth = await self._request("GET", "/api/v1/depth", {"symbol": "SOL_USDC"})
        logger.info(f"SOL_USDC order book:")
        logger.info(f"  Bids: {len(depth.get('bids', []))} levels")
        logger.info(f"  Asks: {len(depth.get('asks', []))} levels")
        if depth.get('bids'):
            logger.info(f"  Best bid: {depth['bids'][0]}")
        if depth.get('asks'):
            logger.info(f"  Best ask: {depth['asks'][0]}")
        
        return True
    
    async def test_authenticated_endpoints(self):
        """Test authenticated endpoints"""
        logger.info("\n=== Testing Authenticated Endpoints ===")
        
        # Test balance query
        logger.info("\n1. Testing GET /api/v1/capital")
        try:
            balances = await self._request("GET", "/api/v1/capital", auth_required=True)
            logger.info("Account balances:")
            if isinstance(balances, dict):
                # Response format: {"USDC": {"available": "0", "locked": "0", "staked": "0"}}
                for symbol, balance_info in balances.items():
                    available = balance_info.get('available', '0')
                    locked = balance_info.get('locked', '0')
                    if available != '0' or locked != '0' or symbol in ['USDC', 'SOL']:
                        logger.info(f"  {symbol}: {available} (locked: {locked})")
            else:
                logger.error(f"Unexpected balance format: {type(balances)}")
                return False
        except Exception as e:
            logger.error(f"Balance query failed: {e}")
            return False
        
        # Test open orders query
        logger.info("\n2. Testing GET /api/v1/orders (open orders)")
        try:
            open_orders = await self._request("GET", "/api/v1/orders", 
                                            params={"symbol": "SOL_USDC"}, 
                                            auth_required=True)
            logger.info(f"Open orders: {len(open_orders) if isinstance(open_orders, list) else 0}")
        except Exception as e:
            logger.error(f"Open orders query failed: {e}")
        
        return True
    
    async def test_order_placement(self):
        """Test order placement"""
        logger.info("\n=== Testing Order Placement ===")
        
        # Get current price first
        ticker = await self._request("GET", "/api/v1/ticker", {"symbol": "SOL_USDC"})
        last_price = Decimal(ticker.get('lastPrice', '0'))
        
        if last_price == 0:
            logger.error("Could not get current price")
            return None
        
        # Place a buy order 20% below market
        buy_price = float(last_price * Decimal('0.8'))
        buy_price = round(buy_price, 2)  # Round to 2 decimals
        
        order_params = {
            "symbol": "SOL_USDC",
            "side": "Bid",
            "orderType": "Limit",
            "price": str(buy_price),
            "quantity": "0.01",  # Minimum allowed amount
            "timeInForce": "GTC"
        }
        
        logger.info(f"Placing test order: Buy 0.01 SOL @ ${buy_price}")
        
        try:
            response = await self._request("POST", "/api/v1/order", 
                                         params=order_params, 
                                         auth_required=True)
            logger.info(f"Order response: {response}")
            
            if response and 'id' in response:
                order_id = response['id']
                logger.info(f"Order placed successfully! Order ID: {order_id}")
                return order_id, response.get('clientId')
            else:
                logger.error(f"Unexpected order response: {response}")
                return None, None
                
        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            return None, None
    
    async def test_order_cancellation(self, order_id: str, symbol: str = "SOL_USDC"):
        """Test order cancellation"""
        logger.info(f"\n=== Testing Order Cancellation ===")
        logger.info(f"Cancelling order ID: {order_id}")
        
        cancel_params = {
            "symbol": symbol,
            "orderId": order_id
        }
        
        try:
            response = await self._request("DELETE", "/api/v1/order", 
                                         params=cancel_params, 
                                         auth_required=True)
            logger.info(f"Cancel response: {response}")
            return True
        except Exception as e:
            logger.error(f"Order cancellation failed: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all tests"""
        logger.info("Starting Backpack Exchange API tests...")
        
        # Test public endpoints
        await self.test_public_endpoints()
        
        # Test authenticated endpoints
        auth_success = await self.test_authenticated_endpoints()
        if not auth_success:
            logger.error("Authentication tests failed, skipping order tests")
            return
        
        # Test order placement
        order_id, client_id = await self.test_order_placement()
        
        if order_id:
            # Wait a bit
            logger.info("\nWaiting 3 seconds before cancellation...")
            await asyncio.sleep(3)
            
            # Test order cancellation
            await self.test_order_cancellation(str(order_id))
        
        logger.info("\nAll tests completed!")


async def main():
    """Main entry point"""
    api_key = os.getenv("BACKPACK_API_KEY")
    api_secret = os.getenv("BACKPACK_API_SECRET")
    
    if not api_key or not api_secret:
        logger.error("Please set BACKPACK_API_KEY and BACKPACK_API_SECRET")
        return
    
    async with BackpackDirectTest(api_key, api_secret) as tester:
        await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())