#!/usr/bin/env python
"""
Simple test script to verify Backpack Exchange authentication.
This script only tests authentication and balance fetching.
"""
import asyncio
import sys
import os
import logging
from decimal import Decimal

# Add hummingbot root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.security import Security
from hummingbot.client.config.config_crypt import ETHKeyFileSecretManger
from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_authentication():
    """Test Backpack Exchange authentication and balance fetching"""
    logger = logging.getLogger("test_backpack_auth")
    
    try:
        # Initialize security with password
        logger.info("Initializing security with password...")
        secrets_manager = ETHKeyFileSecretManger("j17crypto")
        Security.login(secrets_manager)
        
        # Get decrypted API keys
        logger.info("Retrieving API keys from encrypted config...")
        api_keys = Security.api_keys("backpack")
        
        if not api_keys:
            logger.error("No API keys found for backpack connector")
            return
        
        # Map keys correctly
        api_key = api_keys.get("backpack_api_key", "")
        api_secret = api_keys.get("backpack_api_secret", "")
        
        logger.info(f"API Key present: {bool(api_key)}")
        logger.info(f"API Secret present: {bool(api_secret)}")
        logger.info(f"API Key (first 10 chars): {api_key[:10]}..." if api_key else "API Key missing")
        
        # Create client config
        client_config = ClientConfigAdapter(ClientConfigMap())
        
        # Initialize the exchange connector
        logger.info("Creating Backpack Exchange connector...")
        exchange = BackpackExchange(
            client_config_map=client_config,
            api_key=api_key,
            api_secret=api_secret,
            trading_pairs=["SOL-USDC"],
            trading_required=True,
            demo_mode=False  # Explicitly disable demo mode
        )
        
        # Start the exchange (minimal initialization)
        logger.info("Starting exchange network...")
        await exchange.start_network()
        
        # Wait a bit for initialization
        await asyncio.sleep(3)
        
        # Test balance fetching directly
        logger.info("\n=== Testing Direct Balance Fetch ===")
        try:
            await exchange._update_balances()
            
            # Check if we have any balances
            all_balances = exchange.get_all_balances()
            logger.info(f"Balances retrieved: {len(all_balances)} assets")
            
            if all_balances:
                for asset, balance in all_balances.items():
                    logger.info(f"  {asset}: {balance}")
            else:
                logger.warning("No balances returned - this might indicate an authentication issue")
                
            # Also check available balances
            available_balances = exchange.available_balances
            logger.info(f"\nAvailable balances: {len(available_balances)} assets")
            for asset, balance in available_balances.items():
                logger.info(f"  {asset}: {balance}")
                
        except Exception as e:
            logger.error(f"Error fetching balances: {e}", exc_info=True)
        
        # Test API authentication with a simple public endpoint
        logger.info("\n=== Testing Public API ===")
        try:
            markets = await exchange._api_get(
                path_url="/api/v1/markets",
                is_auth_required=False
            )
            logger.info(f"Successfully fetched {len(markets) if isinstance(markets, list) else 0} markets")
        except Exception as e:
            logger.error(f"Error fetching markets: {e}", exc_info=True)
        
        logger.info("\n=== Authentication Test Complete ===")
        
    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
    finally:
        # Clean up
        if 'exchange' in locals():
            await exchange.stop_network()
            logger.info("Exchange stopped")


if __name__ == "__main__":
    asyncio.run(test_authentication())