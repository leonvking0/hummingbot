import base64
import json
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from hummingbot.connector.exchange.backpack.backpack_auth import BackpackAuth
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, RESTRequest


class TestBackpackAuth(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures"""
        # Use test keys (not real keys)
        self.test_api_key = "test_public_key_base64"
        # This is a base64 encoded test private key (32 bytes)
        self.test_api_secret = base64.b64encode(b"test_private_key_32_bytes_long!!").decode()
        self.auth = BackpackAuth(self.test_api_key, self.test_api_secret)

    def test_init(self):
        """Test BackpackAuth initialization"""
        self.assertEqual(self.auth.api_key, self.test_api_key)
        self.assertIsNotNone(self.auth.signing_key)

    def test_generate_auth_string_basic(self):
        """Test basic auth string generation"""
        instruction = "orderQuery"
        timestamp = 1614550000000
        window = 5000
        
        auth_string = self.auth.generate_auth_string(
            instruction=instruction,
            timestamp=timestamp,
            window=window
        )
        
        expected = "instruction=orderQuery&timestamp=1614550000000&window=5000"
        self.assertEqual(auth_string, expected)

    def test_generate_auth_string_with_params(self):
        """Test auth string generation with parameters"""
        instruction = "orderExecute"
        params = {
            "symbol": "SOL_USDC",
            "side": "Bid",
            "orderType": "Limit",
            "price": "20.0",
            "quantity": "1.5"
        }
        timestamp = 1614550000000
        window = 5000
        
        auth_string = self.auth.generate_auth_string(
            instruction=instruction,
            params=params,
            timestamp=timestamp,
            window=window
        )
        
        # Parameters should be sorted alphabetically
        expected = (
            "instruction=orderExecute&"
            "orderType=Limit&price=20.0&quantity=1.5&side=Bid&symbol=SOL_USDC&"
            "timestamp=1614550000000&window=5000"
        )
        self.assertEqual(auth_string, expected)

    def test_generate_auth_string_with_json_params(self):
        """Test auth string generation with JSON string parameters"""
        instruction = "orderExecute"
        params_json = json.dumps({
            "symbol": "SOL_USDC",
            "side": "Bid",
            "orderType": "Limit"
        })
        timestamp = 1614550000000
        window = 5000
        
        auth_string = self.auth.generate_auth_string(
            instruction=instruction,
            params=params_json,
            timestamp=timestamp,
            window=window
        )
        
        expected = (
            "instruction=orderExecute&"
            "orderType=Limit&side=Bid&symbol=SOL_USDC&"
            "timestamp=1614550000000&window=5000"
        )
        self.assertEqual(auth_string, expected)

    def test_get_signature(self):
        """Test signature generation"""
        message = "test_message"
        signature = self.auth.get_signature(message)
        
        # Signature should be base64 encoded
        self.assertIsInstance(signature, str)
        # Base64 decoded signature should be 64 bytes (ED25519 signature size)
        decoded_sig = base64.b64decode(signature)
        self.assertEqual(len(decoded_sig), 64)

    def test_get_instruction_for_endpoint(self):
        """Test instruction mapping for different endpoints"""
        test_cases = [
            ("/api/v1/account", None, "accountQuery"),
            ("/api/v1/capital", None, "balanceQuery"),
            ("/api/v1/capital/collateral", None, "collateralQuery"),
            ("/api/v1/order", "POST", "orderExecute"),
            ("/api/v1/order", "DELETE", "orderCancel"),
            ("/api/v1/orders", None, "orderQueryAll"),
            ("/api/v1/fills", None, "fillHistoryQueryAll"),
            ("/api/v1/unknown", None, "accountQuery"),  # Default
        ]
        
        for url, method, expected_instruction in test_cases:
            instruction = self.auth._get_instruction_for_endpoint(url, method)
            self.assertEqual(instruction, expected_instruction,
                           f"Failed for URL: {url}, method: {method}")

    @patch("time.time")
    async def test_rest_authenticate(self, mock_time):
        """Test REST request authentication"""
        mock_time.return_value = 1614550.0  # Returns seconds, will be converted to ms
        
        # Create a test request
        request = RESTRequest(
            method=RESTMethod.POST,
            url="/api/v1/order",
            data={"symbol": "SOL_USDC", "side": "Bid", "quantity": "1.0"}
        )
        
        # Authenticate the request
        authenticated_request = await self.auth.rest_authenticate(request)
        
        # Check headers were added
        self.assertIn("X-API-KEY", authenticated_request.headers)
        self.assertIn("X-SIGNATURE", authenticated_request.headers)
        self.assertIn("X-TIMESTAMP", authenticated_request.headers)
        self.assertIn("X-WINDOW", authenticated_request.headers)
        
        # Verify header values
        self.assertEqual(authenticated_request.headers["X-API-KEY"], self.test_api_key)
        self.assertEqual(authenticated_request.headers["X-TIMESTAMP"], "1614550000")
        self.assertEqual(authenticated_request.headers["X-WINDOW"], "5000")
        
        # Signature should be base64 encoded
        signature = authenticated_request.headers["X-SIGNATURE"]
        base64.b64decode(signature)  # Should not raise exception

    async def test_ws_authenticate(self):
        """Test WebSocket authentication (should return request unchanged)"""
        from hummingbot.core.web_assistant.connections.data_types import WSRequest
        
        request = WSRequest(payload={"test": "data"})
        authenticated_request = await self.auth.ws_authenticate(request)
        
        # WebSocket auth is handled differently, request should be unchanged
        self.assertEqual(request, authenticated_request)

    def test_get_ws_auth_payload(self):
        """Test WebSocket authentication payload generation"""
        streams = ["account.orderUpdate", "account.positionUpdate"]
        
        with patch("time.time", return_value=1614550.0):
            auth_payload = self.auth.get_ws_auth_payload(streams)
        
        # Check payload structure
        self.assertEqual(auth_payload["method"], "SUBSCRIBE")
        self.assertEqual(auth_payload["params"], streams)
        self.assertIn("signature", auth_payload)
        
        # Signature should contain 4 elements
        signature_parts = auth_payload["signature"]
        self.assertEqual(len(signature_parts), 4)
        self.assertEqual(signature_parts[0], self.test_api_key)  # API key
        self.assertIsInstance(signature_parts[1], str)  # Signature
        self.assertEqual(signature_parts[2], "1614550000")  # Timestamp
        self.assertEqual(signature_parts[3], "5000")  # Window

    def test_generate_auth_string_empty_params(self):
        """Test auth string generation with empty parameters"""
        instruction = "accountQuery"
        params = {}
        timestamp = 1614550000000
        window = 5000
        
        auth_string = self.auth.generate_auth_string(
            instruction=instruction,
            params=params,
            timestamp=timestamp,
            window=window
        )
        
        expected = "instruction=accountQuery&timestamp=1614550000000&window=5000"
        self.assertEqual(auth_string, expected)

    def test_generate_auth_string_none_params(self):
        """Test auth string generation with None parameters"""
        instruction = "accountQuery"
        params = None
        timestamp = 1614550000000
        window = 5000
        
        auth_string = self.auth.generate_auth_string(
            instruction=instruction,
            params=params,
            timestamp=timestamp,
            window=window
        )
        
        expected = "instruction=accountQuery&timestamp=1614550000000&window=5000"
        self.assertEqual(auth_string, expected)

    def test_invalid_json_params(self):
        """Test handling of invalid JSON parameters"""
        instruction = "orderExecute"
        params = "invalid json"
        timestamp = 1614550000000
        window = 5000
        
        # Should handle gracefully
        auth_string = self.auth.generate_auth_string(
            instruction=instruction,
            params=params,
            timestamp=timestamp,
            window=window
        )
        
        # Should just include instruction, timestamp, and window
        expected = "instruction=orderExecute&timestamp=1614550000000&window=5000"
        self.assertEqual(auth_string, expected)


if __name__ == "__main__":
    unittest.main()