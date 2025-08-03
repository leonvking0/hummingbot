import asyncio
import base64
import json
import logging
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock, Mock
from decimal import Decimal

from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
from hummingbot.connector.exchange.backpack.backpack_auth import BackpackAuth
from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.core.web_assistant.connections.data_types import RESTRequest
from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_helpers import ClientConfigAdapter


class TestBackpackAuthSecurity(unittest.TestCase):
    """Test authentication security for Backpack Exchange"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ev_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(cls.ev_loop)
    
    def setUp(self):
        """Set up test fixtures"""
        self.api_key = "test_api_key"
        # Use a valid base64 encoded string (32 bytes = 256 bits for Ed25519)
        self.api_secret = "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
        
        self.auth = BackpackAuth(
            api_key=self.api_key,
            api_secret=self.api_secret
        )
    
    def test_signature_generation(self):
        """Test that signature generation works correctly"""
        # Test signature generation for different instructions
        message = "instruction=account&timestamp=1234567890&window=1000"
        
        sig1 = self.auth.get_signature(message)
        sig2 = self.auth.get_signature(message)
        
        # Same message should produce same signature
        self.assertEqual(sig1, sig2)
        
        # Different message should produce different signature
        message2 = "instruction=order&timestamp=1234567890&window=1000"
        sig3 = self.auth.get_signature(message2)
        self.assertNotEqual(sig1, sig3)
        
        # Signature should be base64 encoded
        try:
            base64.b64decode(sig1)
        except Exception as e:
            self.fail(f"Signature is not valid base64: {e}")
    
    def test_auth_string_generation(self):
        """Test auth string generation for signing"""
        # Test basic auth string
        auth_str = self.auth.generate_auth_string(
            instruction="account",
            timestamp=1234567890,
            window=1000
        )
        
        self.assertIn("instruction=account", auth_str)
        self.assertIn("timestamp=1234567890", auth_str)
        self.assertIn("window=1000", auth_str)
        
        # Test with parameters
        params = {"symbol": "SOL_USDC", "quantity": "1.0"}
        auth_str_with_params = self.auth.generate_auth_string(
            instruction="order",
            params=params,
            timestamp=1234567890,
            window=1000
        )
        
        self.assertIn("instruction=order", auth_str_with_params)
        self.assertIn("quantity=1.0", auth_str_with_params)
        self.assertIn("symbol=SOL_USDC", auth_str_with_params)
        
        # Parameters should be sorted alphabetically
        self.assertLess(
            auth_str_with_params.index("quantity"),
            auth_str_with_params.index("symbol"),
            "Parameters not sorted alphabetically"
        )
    
    def test_rest_authenticate(self):
        """Test REST request authentication"""
        request = RESTRequest(
            method="GET",
            url="https://api.backpack.exchange/api/v1/account"
        )
        
        # Run async authentication
        authenticated_request = self.ev_loop.run_until_complete(
            self.auth.rest_authenticate(request)
        )
        
        # Check that auth headers are added (headers are uppercase)
        self.assertIn("X-API-KEY", authenticated_request.headers)
        self.assertIn("X-SIGNATURE", authenticated_request.headers)
        self.assertIn("X-TIMESTAMP", authenticated_request.headers)
        self.assertIn("X-WINDOW", authenticated_request.headers)
        
        # Verify API key is set correctly
        self.assertEqual(authenticated_request.headers["X-API-KEY"], self.api_key)
        
        # Verify timestamp is recent
        timestamp = int(authenticated_request.headers["X-TIMESTAMP"])
        current_time = int(time.time() * 1000)
        time_diff = abs(current_time - timestamp)
        self.assertLess(time_diff, 5000, "Timestamp too old")
        
        # Verify window is set
        window = int(authenticated_request.headers["X-WINDOW"])
        self.assertEqual(window, CONSTANTS.DEFAULT_REQUEST_WINDOW)
    
    def test_websocket_authenticate(self):
        """Test WebSocket authentication payload generation"""
        streams = ["depth.SOL_USDC", "trade.SOL_USDC"]
        
        # Generate WebSocket auth payload
        auth_payload = self.auth.get_ws_auth_payload(streams)
        
        # Check structure
        self.assertIn("method", auth_payload)
        self.assertEqual(auth_payload["method"], "SUBSCRIBE")
        
        self.assertIn("params", auth_payload)
        self.assertEqual(auth_payload["params"], streams)
        
        self.assertIn("signature", auth_payload)
        self.assertIsInstance(auth_payload["signature"], list)
        self.assertEqual(len(auth_payload["signature"]), 4)
        
        # Check signature components
        sig_components = auth_payload["signature"]
        self.assertEqual(sig_components[0], self.api_key)  # API key
        self.assertIsInstance(sig_components[1], str)  # Signature
        self.assertIsInstance(sig_components[2], (int, str))  # Timestamp (can be string)
        self.assertIsInstance(sig_components[3], (int, str))  # Window (can be string)
    
    def test_instruction_determination_security(self):
        """Test secure instruction determination from API paths"""
        # Test valid endpoints (using actual instruction names from implementation)
        valid_endpoints = [
            ("https://api.backpack.exchange/api/v1/account", "accountQuery"),
            ("https://api.backpack.exchange/api/v1/capital", "balanceQuery"),
            ("https://api.backpack.exchange/api/v1/orders", "orderQueryAll"),
        ]
        
        for url, expected_instruction in valid_endpoints:
            instruction = self.auth._get_instruction_for_endpoint(url)
            self.assertEqual(instruction, expected_instruction)
        
        # Test path traversal protection
        invalid_urls = [
            "https://api.backpack.exchange/../../../etc/passwd",
            "https://api.backpack.exchange/api/v1/../../admin",
        ]
        
        for url in invalid_urls:
            with self.assertRaises(ValueError) as context:
                self.auth._get_instruction_for_endpoint(url)
            self.assertIn("Invalid URL detected", str(context.exception))
    
    def test_no_sensitive_data_logged(self):
        """Test that sensitive data is not logged"""
        # Set up a custom logger to capture log messages
        log_messages = []
        
        class TestHandler(logging.Handler):
            def emit(self, record):
                log_messages.append(self.format(record))
        
        handler = TestHandler()
        test_logger = logging.getLogger("test_auth")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.DEBUG)
        
        # Patch the logger in the auth module
        with patch.object(self.auth, '_logger', test_logger):
            # Generate auth string and signature
            auth_string = self.auth.generate_auth_string(
                instruction="order",
                params={"symbol": "SOL_USDC", "quantity": "1.0"},
                timestamp=1234567890,
                window=1000
            )
            signature = self.auth.get_signature(auth_string)
            
            # Create a request and authenticate it
            request = RESTRequest(
                method="POST",
                url="https://api.backpack.exchange/api/v1/order",
                data=json.dumps({"symbol": "SOL_USDC", "quantity": "1.0"})
            )
            
            self.ev_loop.run_until_complete(self.auth.rest_authenticate(request))
        
        # Check logs for sensitive data
        all_logs = " ".join(log_messages)
        
        # API key and signature should not be in logs
        self.assertNotIn(self.api_key, all_logs, "API key found in logs!")
        self.assertNotIn(signature, all_logs, "Signature found in logs!")
        self.assertNotIn(self.api_secret, all_logs, "API secret found in logs!")
        
        # Header values should not be logged
        self.assertNotIn("X-API-Key", all_logs, "X-API-Key header in logs!")
        self.assertNotIn("X-Signature", all_logs, "X-Signature header in logs!")
    
    def test_key_memory_cleanup(self):
        """Test that keys can be cleared from memory"""
        # Create auth instance
        auth = BackpackAuth(
            api_key="test_key",
            api_secret=self.api_secret
        )
        
        # Verify signing key exists
        self.assertIsNotNone(auth._signing_key)
        
        # Clear keys
        auth.clear_keys()
        
        # Verify key is cleared
        self.assertIsNone(auth._signing_key)
        
        # Verify signature generation fails after clearing
        with self.assertRaises(ValueError) as context:
            auth.get_signature("test message")
        self.assertIn("Signing key not available", str(context.exception))
    
    def test_request_window_default(self):
        """Test that default request window is used correctly"""
        # Generate auth string without specifying window
        auth_str = self.auth.generate_auth_string(
            instruction="account",
            timestamp=1234567890
        )
        
        # Should use default window
        self.assertIn(f"window={CONSTANTS.DEFAULT_REQUEST_WINDOW}", auth_str)
        
        # Verify default window value
        self.assertEqual(CONSTANTS.DEFAULT_REQUEST_WINDOW, 1000)
    
    def test_demo_mode_in_exchange(self):
        """Test that demo mode is handled correctly in the exchange"""
        client_config_map = ClientConfigAdapter(ClientConfigMap())
        
        # Test without demo mode
        exchange_prod = BackpackExchange(
            client_config_map=client_config_map,
            api_key=self.api_key,
            api_secret=self.api_secret,
            trading_pairs=["SOL-USDC"]
        )
        
        self.assertFalse(exchange_prod._demo_mode)
        
        # Test with demo mode
        exchange_demo = BackpackExchange(
            client_config_map=client_config_map,
            api_key=self.api_key,
            api_secret=self.api_secret,
            trading_pairs=["SOL-USDC"],
            demo_mode=True
        )
        
        self.assertTrue(exchange_demo._demo_mode)


if __name__ == "__main__":
    unittest.main()