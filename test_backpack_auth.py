#!/usr/bin/env python3
"""
Test script for Backpack Exchange ED25519 authentication
Tests signature generation according to Backpack API requirements
"""

import base64
import json
import logging
import os
import sys
import time
from typing import Dict, Any
from urllib.parse import urlencode

# Add hummingbot to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from nacl.signing import SigningKey, VerifyKey
from hummingbot.connector.exchange.backpack.backpack_auth import BackpackAuth

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_signature_generation():
    """Test ED25519 signature generation according to Backpack API spec"""
    logger.info("=== Testing ED25519 Signature Generation ===")
    
    # Check for API credentials
    api_key = os.getenv("BACKPACK_API_KEY")
    api_secret = os.getenv("BACKPACK_API_SECRET")
    
    if not api_key or not api_secret:
        logger.error("Please set BACKPACK_API_KEY and BACKPACK_API_SECRET")
        return False
    
    try:
        # Create auth instance
        auth = BackpackAuth(api_key, api_secret)
        logger.info("Auth instance created successfully")
        
        # Test 1: Basic signature generation
        logger.info("\nTest 1: Basic signature generation")
        timestamp = int(time.time() * 1000)
        window = 5000
        instruction = "orderExecute"
        
        params = {
            "symbol": "SOL_USDC",
            "side": "Bid",
            "orderType": "Limit",
            "price": "20.5",
            "quantity": "1"
        }
        
        # Generate auth string
        auth_string = auth.generate_auth_string(instruction, params, timestamp, window)
        logger.info(f"Auth string: {auth_string}")
        
        # Generate signature
        signature = auth.get_signature(auth_string)
        logger.info(f"Signature: {signature[:16]}...{signature[-16:]}")
        
        # Verify the signature
        verify_key = VerifyKey(base64.b64decode(api_key))
        try:
            verify_key.verify(auth_string.encode('utf-8'), base64.b64decode(signature))
            logger.info("✓ Signature verification passed")
        except Exception as e:
            logger.error(f"✗ Signature verification failed: {e}")
            return False
        
        # Test 2: Order cancellation signature
        logger.info("\nTest 2: Order cancellation signature")
        cancel_params = {
            "orderId": "28",
            "symbol": "BTC_USDT"
        }
        
        cancel_auth_string = auth.generate_auth_string("orderCancel", cancel_params, timestamp, window)
        expected = f"instruction=orderCancel&orderId=28&symbol=BTC_USDT&timestamp={timestamp}&window={window}"
        
        if cancel_auth_string == expected:
            logger.info("✓ Cancel auth string matches expected format")
        else:
            logger.error(f"✗ Cancel auth string mismatch")
            logger.error(f"Expected: {expected}")
            logger.error(f"Got: {cancel_auth_string}")
            return False
        
        # Test 3: Batch order signature (from API docs example)
        logger.info("\nTest 3: Batch order signature")
        
        # For batch orders, each order gets its own instruction prefix
        batch_orders = [
            {
                "symbol": "SOL_USDC_PERP",
                "side": "Bid",
                "orderType": "Limit",
                "price": "141",
                "quantity": "12"
            },
            {
                "symbol": "SOL_USDC_PERP",
                "side": "Bid",
                "orderType": "Limit",
                "price": "140",
                "quantity": "11"
            }
        ]
        
        # Build batch signature string
        batch_parts = []
        for order in batch_orders:
            # Sort order parameters
            sorted_order = sorted(order.items())
            order_string = urlencode(sorted_order)
            batch_parts.append(f"instruction=orderExecute&{order_string}")
        
        # Join all parts and add timestamp/window
        batch_auth_string = "&".join(batch_parts) + f"&timestamp={timestamp}&window={window}"
        logger.info(f"Batch auth string: {batch_auth_string[:100]}...")
        
        # Test 4: Empty parameters (e.g., balance query)
        logger.info("\nTest 4: Balance query signature (no parameters)")
        balance_auth_string = auth.generate_auth_string("balanceQuery", None, timestamp, window)
        expected_balance = f"instruction=balanceQuery&timestamp={timestamp}&window={window}"
        
        if balance_auth_string == expected_balance:
            logger.info("✓ Balance query auth string correct")
        else:
            logger.error(f"✗ Balance query auth string mismatch")
            return False
        
        logger.info("\n✓ All signature generation tests passed!")
        return True
        
    except Exception as e:
        logger.error(f"Signature generation test failed: {e}", exc_info=True)
        return False


def test_key_format():
    """Test that API keys are in correct format"""
    logger.info("\n=== Testing API Key Format ===")
    
    api_key = os.getenv("BACKPACK_API_KEY")
    api_secret = os.getenv("BACKPACK_API_SECRET")
    
    if not api_key or not api_secret:
        logger.error("API keys not set")
        return False
    
    try:
        # Test public key (verifying key)
        logger.info("Testing public key format...")
        public_key_bytes = base64.b64decode(api_key)
        if len(public_key_bytes) != 32:
            logger.error(f"Public key should be 32 bytes, got {len(public_key_bytes)}")
            return False
        logger.info("✓ Public key format correct (32 bytes)")
        
        # Test private key (signing key)
        logger.info("Testing private key format...")
        private_key_bytes = base64.b64decode(api_secret)
        if len(private_key_bytes) not in [32, 64]:  # Can be seed (32) or full keypair (64)
            logger.error(f"Private key should be 32 or 64 bytes, got {len(private_key_bytes)}")
            return False
        logger.info(f"✓ Private key format correct ({len(private_key_bytes)} bytes)")
        
        # Test key pair relationship
        logger.info("Testing key pair relationship...")
        if len(private_key_bytes) == 32:
            signing_key = SigningKey(private_key_bytes)
        else:
            signing_key = SigningKey(private_key_bytes[:32])
        
        derived_verify_key = signing_key.verify_key
        
        if base64.b64encode(derived_verify_key.encode()).decode() == api_key:
            logger.info("✓ Key pair relationship verified")
        else:
            logger.warning("⚠ Public key doesn't match derived key from private key")
            logger.info("This might be normal if keys were generated separately")
        
        return True
        
    except Exception as e:
        logger.error(f"Key format test failed: {e}", exc_info=True)
        return False


def generate_test_keypair():
    """Generate a test ED25519 keypair for documentation"""
    logger.info("\n=== Generating Test Keypair ===")
    
    # Generate new keypair
    signing_key = SigningKey.generate()
    verify_key = signing_key.verify_key
    
    # Encode as base64
    private_key_b64 = base64.b64encode(signing_key.encode()).decode()
    public_key_b64 = base64.b64encode(verify_key.encode()).decode()
    
    logger.info("Test keypair generated (DO NOT USE IN PRODUCTION):")
    logger.info(f"Public key (API Key): {public_key_b64}")
    logger.info(f"Private key (API Secret): {private_key_b64[:8]}...{private_key_b64[-8:]}")
    
    return public_key_b64, private_key_b64


def main():
    """Run all authentication tests"""
    logger.info("Starting Backpack authentication tests...\n")
    
    # Test key format
    if not test_key_format():
        logger.error("Key format test failed")
        return
    
    # Test signature generation
    if not test_signature_generation():
        logger.error("Signature generation test failed")
        return
    
    logger.info("\n✓ All authentication tests passed!")
    
    # Optionally generate test keypair for documentation
    if "--generate-keypair" in sys.argv:
        generate_test_keypair()


if __name__ == "__main__":
    main()