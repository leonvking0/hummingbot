import asyncio
import base64
import json
import logging
import time
import unittest
from typing import Any, Dict
from unittest.mock import MagicMock, patch, PropertyMock
from urllib.parse import urlencode

import nacl.encoding
import nacl.signing
from nacl.signing import SigningKey

from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.connector.exchange.backpack.backpack_auth import BackpackAuth
from hummingbot.core.web_assistant.connections.data_types import RESTRequest


class TestBackpackAuthSecurity(unittest.TestCase):
    """Security-focused test cases for Backpack Exchange authentication"""
    
    def setUp(self) -> None:
        """Set up test fixtures"""
        super().setUp()
        
        # Generate test keys
        self.signing_key = SigningKey.generate()
        self.api_key = base64.b64encode(bytes(self.signing_key.verify_key)).decode('utf-8')
        self.api_secret = base64.b64encode(bytes(self.signing_key)).decode('utf-8')
        
        # Create auth instance
        self.auth = BackpackAuth(self.api_key, self.api_secret)
        
        # Set up logging capture
        self.log_records = []
        self.log_handler = MagicMock()
        self.log_handler.handle = lambda record: self.log_records.append(record)
        
    def tearDown(self) -> None:
        """Clean up after tests"""
        super().tearDown()
        # Ensure keys are cleared
        if hasattr(self, 'auth'):
            self.auth.clear_keys()
    
    # ========== Task 1.1: Sensitive Data Logging Tests ==========
    
    def test_no_api_keys_in_logs(self):
        """Test that API keys are never logged"""
        with patch('hummingbot.connector.exchange.backpack.backpack_auth.logging') as mock_logging:
            mock_logger = MagicMock()
            mock_logging.getLogger.return_value = mock_logger
            
            # Create new auth instance with mocked logger
            auth = BackpackAuth(self.api_key, self.api_secret)
            
            # Create and apply auth to a request
            request = RESTRequest(
                method="GET",
                url="https://api.backpack.exchange/api/v1/account",
                headers={}
            )
            
            asyncio.get_event_loop().run_until_complete(auth.rest_authenticate(request))
            
            # Check all log calls
            for call in mock_logger.info.call_args_list + mock_logger.debug.call_args_list:
                log_message = str(call)
                # API key should never appear in full
                self.assertNotIn(self.api_key, log_message)
                # Even partial API key (first 10 chars) should not appear
                if len(self.api_key) > 10:
                    self.assertNotIn(self.api_key[:10], log_message)
    
    def test_no_signatures_in_logs(self):
        """Test that signatures are never logged"""
        with patch('hummingbot.connector.exchange.backpack.backpack_auth.logging') as mock_logging:
            mock_logger = MagicMock()
            mock_logging.getLogger.return_value = mock_logger
            
            auth = BackpackAuth(self.api_key, self.api_secret)
            
            # Generate a signature
            test_message = "test_message"
            signature = auth.get_signature(test_message)
            
            # Apply auth to request
            request = RESTRequest(
                method="GET",
                url="https://api.backpack.exchange/api/v1/account",
                headers={}
            )
            asyncio.get_event_loop().run_until_complete(auth.rest_authenticate(request))
            
            # Check logs don't contain signature
            for call in mock_logger.info.call_args_list + mock_logger.debug.call_args_list:
                log_message = str(call)
                self.assertNotIn(signature, log_message)
    
    def test_no_auth_strings_in_logs(self):
        """Test that auth strings are never logged"""
        with patch('hummingbot.connector.exchange.backpack.backpack_auth.logging') as mock_logging:
            mock_logger = MagicMock()
            mock_logging.getLogger.return_value = mock_logger
            
            auth = BackpackAuth(self.api_key, self.api_secret)
            
            # Generate auth string
            auth_string = auth.generate_auth_string(
                instruction="accountQuery",
                params={"test": "value"},
                timestamp=int(time.time() * 1000),
                window=1000
            )
            
            # Apply auth
            request = RESTRequest(
                method="GET",
                url="https://api.backpack.exchange/api/v1/account",
                headers={}
            )
            asyncio.get_event_loop().run_until_complete(auth.rest_authenticate(request))
            
            # Check auth string not in logs
            for call in mock_logger.info.call_args_list + mock_logger.debug.call_args_list:
                log_message = str(call)
                self.assertNotIn(auth_string, log_message)
    
    def test_sanitized_logging_provides_info(self):
        """Test that sanitized logging still provides useful information"""
        with patch('hummingbot.connector.exchange.backpack.backpack_auth.logging') as mock_logging:
            mock_logger = MagicMock()
            mock_logging.getLogger.return_value = mock_logger
            
            auth = BackpackAuth(self.api_key, self.api_secret)
            
            request = RESTRequest(
                method="POST",
                url="https://api.backpack.exchange/api/v1/order",
                headers={}
            )
            auth._current_method = "POST"
            asyncio.get_event_loop().run_until_complete(auth.rest_authenticate(request))
            
            # Should log method and instruction without sensitive data
            mock_logger.info.assert_called()
            call_args = str(mock_logger.info.call_args_list)
            self.assertIn("POST", call_args)
            self.assertIn("orderExecute", call_args)
    
    # ========== Task 1.2: Request Window Tests ==========
    
    def test_default_request_window_is_1000ms(self):
        """Test that default request window is 1000ms"""
        self.assertEqual(CONSTANTS.DEFAULT_REQUEST_WINDOW, 1000)
    
    def test_max_request_window_is_5000ms(self):
        """Test that maximum request window is 5000ms"""
        self.assertEqual(CONSTANTS.MAX_REQUEST_WINDOW, 5000)
    
    def test_request_uses_correct_window(self):
        """Test that requests use the correct window value"""
        request = RESTRequest(
            method="GET",
            url="https://api.backpack.exchange/api/v1/account",
            headers={}
        )
        
        asyncio.get_event_loop().run_until_complete(self.auth.rest_authenticate(request))
        
        # Check window header is set correctly
        self.assertIn(CONSTANTS.HEADER_WINDOW, request.headers)
        window_value = int(request.headers[CONSTANTS.HEADER_WINDOW])
        self.assertEqual(window_value, CONSTANTS.DEFAULT_REQUEST_WINDOW)
    
    def test_window_value_in_auth_string(self):
        """Test that window value is included in auth string"""
        timestamp = int(time.time() * 1000)
        window = 1000
        
        auth_string = self.auth.generate_auth_string(
            instruction="accountQuery",
            timestamp=timestamp,
            window=window
        )
        
        # Auth string should contain window value
        self.assertIn(str(window), auth_string)
    
    # ========== Task 1.3: Secure Key Handling Tests ==========
    
    def test_destructor_clears_keys(self):
        """Test that __del__ destructor clears sensitive keys"""
        auth = BackpackAuth(self.api_key, self.api_secret)
        
        # Store reference to signing key
        signing_key_ref = auth._signing_key
        
        # Call destructor
        auth.__del__()
        
        # Check key is cleared
        self.assertIsNone(auth._signing_key)
    
    def test_clear_keys_method_zeros_data(self):
        """Test that clear_keys() method zeros sensitive data"""
        auth = BackpackAuth(self.api_key, self.api_secret)
        
        # Verify key exists initially
        self.assertIsNotNone(auth._signing_key)
        
        # Clear keys
        auth.clear_keys()
        
        # Verify key is cleared
        self.assertIsNone(auth._signing_key)
    
    def test_get_signature_validates_key(self):
        """Test that get_signature() validates key availability"""
        auth = BackpackAuth(self.api_key, self.api_secret)
        
        # Clear the key
        auth._signing_key = None
        
        # Should raise error when key not available
        with self.assertRaises(ValueError) as context:
            auth.get_signature("test_message")
        
        self.assertIn("Signing key not available", str(context.exception))
    
    def test_get_signature_error_handling(self):
        """Test that get_signature() handles errors properly"""
        auth = BackpackAuth(self.api_key, self.api_secret)
        
        # Mock signing to raise an error
        with patch.object(auth._signing_key, 'sign', side_effect=Exception("Test error")):
            with patch('hummingbot.connector.exchange.backpack.backpack_auth.logging') as mock_logging:
                mock_logger = MagicMock()
                mock_logging.getLogger.return_value = mock_logger
                auth._logger = mock_logger
                
                with self.assertRaises(Exception):
                    auth.get_signature("test_message")
                
                # Should log the error
                mock_logger.error.assert_called()
    
    # ========== Task 1.4: Demo Mode Security Tests ==========
    
    def test_demo_mode_requires_explicit_flag(self):
        """Test that demo mode requires explicit flag"""
        from hummingbot.client.config.client_config_map import ClientConfigMap
        from hummingbot.client.config.config_helpers import ClientConfigAdapter
        from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
        
        client_config = ClientConfigAdapter(ClientConfigMap())
        
        # Without demo_mode flag, should be False even without credentials
        exchange = BackpackExchange(
            client_config_map=client_config,
            api_key="",
            api_secret="",
            trading_pairs=["SOL-USDC"]
        )
        self.assertFalse(exchange._demo_mode)
        
        # With explicit demo_mode=True
        exchange = BackpackExchange(
            client_config_map=client_config,
            api_key="",
            api_secret="",
            trading_pairs=["SOL-USDC"],
            demo_mode=True
        )
        self.assertTrue(exchange._demo_mode)
        
        # With explicit demo_mode=False
        exchange = BackpackExchange(
            client_config_map=client_config,
            api_key="",
            api_secret="",
            trading_pairs=["SOL-USDC"],
            demo_mode=False
        )
        self.assertFalse(exchange._demo_mode)
    
    def test_error_when_trading_without_credentials(self):
        """Test that error is raised when trading enabled without credentials"""
        from hummingbot.client.config.client_config_map import ClientConfigMap
        from hummingbot.client.config.config_helpers import ClientConfigAdapter
        from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
        
        client_config = ClientConfigAdapter(ClientConfigMap())
        
        # Should raise error when trading_required=True without credentials
        with self.assertRaises(ValueError) as context:
            BackpackExchange(
                client_config_map=client_config,
                api_key="",
                api_secret="",
                trading_pairs=["SOL-USDC"],
                trading_required=True
            )
        
        self.assertIn("API credentials required when trading is enabled", str(context.exception))
    
    def test_clear_mode_logging(self):
        """Test that mode is clearly logged"""
        from hummingbot.client.config.client_config_map import ClientConfigMap
        from hummingbot.client.config.config_helpers import ClientConfigAdapter
        from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
        
        client_config = ClientConfigAdapter(ClientConfigMap())
        
        with patch('hummingbot.connector.exchange.backpack.backpack_exchange.BackpackExchange.logger') as mock_logger_method:
            mock_logger = MagicMock()
            mock_logger_method.return_value = mock_logger
            
            # Test production mode logging
            exchange = BackpackExchange(
                client_config_map=client_config,
                api_key=self.api_key,
                api_secret=self.api_secret,
                trading_pairs=["SOL-USDC"],
                demo_mode=False
            )
            
            mock_logger.info.assert_called()
            call_args = str(mock_logger.info.call_args)
            self.assertIn("PRODUCTION MODE", call_args)
            
            # Reset mock
            mock_logger.reset_mock()
            
            # Test demo mode logging
            exchange = BackpackExchange(
                client_config_map=client_config,
                api_key="",
                api_secret="",
                trading_pairs=["SOL-USDC"],
                demo_mode=True
            )
            
            mock_logger.info.assert_called()
            call_args = str(mock_logger.info.call_args)
            self.assertIn("DEMO MODE", call_args)
    
    # ========== Task 1.5: Instruction Determination Tests ==========
    
    def test_path_traversal_blocked(self):
        """Test that path traversal attempts are blocked"""
        # Test with .. in URL
        with self.assertRaises(ValueError) as context:
            self.auth._get_instruction_for_endpoint("https://api.backpack.exchange/../../../etc/passwd")
        self.assertIn("Invalid URL detected", str(context.exception))
        
        # Test with // in URL
        with self.assertRaises(ValueError) as context:
            self.auth._get_instruction_for_endpoint("https://api.backpack.exchange//admin//api")
        self.assertIn("Invalid URL detected", str(context.exception))
    
    def test_correct_instruction_mapping(self):
        """Test correct instruction mapping for all endpoints"""
        test_cases = [
            ("https://api.backpack.exchange/api/v1/account", "accountQuery"),
            ("https://api.backpack.exchange/api/v1/capital", "balanceQuery"),
            ("https://api.backpack.exchange/api/v1/capital/collateral", "collateralQuery"),
            ("https://api.backpack.exchange/api/v1/orders", "orderQueryAll"),
            ("https://api.backpack.exchange/api/v1/fills", "fillHistoryQueryAll"),
            ("https://api.backpack.exchange/api/v1/deposits", "depositQueryAll"),
            ("https://api.backpack.exchange/api/v1/withdrawals", "withdrawalQueryAll"),
        ]
        
        for url, expected_instruction in test_cases:
            instruction = self.auth._get_instruction_for_endpoint(url)
            self.assertEqual(instruction, expected_instruction, f"Failed for URL: {url}")
    
    def test_method_based_routing_for_orders(self):
        """Test method-based routing for order endpoints"""
        # Test POST for order execution
        self.auth._current_method = "POST"
        instruction = self.auth._get_instruction_for_endpoint("https://api.backpack.exchange/api/v1/order")
        self.assertEqual(instruction, "orderExecute")
        
        # Test DELETE for order cancellation
        self.auth._current_method = "DELETE"
        instruction = self.auth._get_instruction_for_endpoint("https://api.backpack.exchange/api/v1/order")
        self.assertEqual(instruction, "orderCancel")
        
        # Test GET for order query
        self.auth._current_method = "GET"
        instruction = self.auth._get_instruction_for_endpoint("https://api.backpack.exchange/api/v1/order")
        self.assertEqual(instruction, "orderQuery")
    
    def test_unknown_endpoint_handling(self):
        """Test handling of unknown endpoints"""
        with patch('hummingbot.connector.exchange.backpack.backpack_auth.logging') as mock_logging:
            mock_logger = MagicMock()
            mock_logging.getLogger.return_value = mock_logger
            self.auth._logger = mock_logger
            
            # Unknown endpoint should return default and log warning
            instruction = self.auth._get_instruction_for_endpoint("https://api.backpack.exchange/api/v1/unknown")
            
            self.assertEqual(instruction, "accountQuery")
            mock_logger.warning.assert_called()
            call_args = str(mock_logger.warning.call_args)
            self.assertIn("Unknown endpoint", call_args)


if __name__ == "__main__":
    unittest.main()