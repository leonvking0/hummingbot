import asyncio
import hashlib
import hmac
from typing import Awaitable
from unittest import TestCase
from unittest.mock import MagicMock

from hummingbot.connector.exchange.backpack_exchange.backpack_auth import BackpackAuth
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, RESTRequest, WSJSONRequest


class BackpackAuthTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.api_key = "key"
        self.secret_key = "secret"
        self.mock_time = MagicMock()
        self.mock_time.time.return_value = 1000
        self.auth = BackpackAuth(api_key=self.api_key, secret_key=self.secret_key, time_provider=self.mock_time)

    def async_run(self, coroutine: Awaitable):
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(asyncio.wait_for(coroutine, 1))

    def test_generate_signature(self):
        # Verify signature generation logic directly without comparing to a hardcoded hash
        timestamp = "1692693725000"
        nonce = "1692693725000"
        method = RESTMethod.GET
        url = "/api/v1/orders"

        # Create the expected message
        message = f"{timestamp}{nonce}{method.value}{url}"

        # Calculate expected signature
        expected_signature = hmac.new(
            self.secret_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        # Compare with actual signature
        actual_signature = self.auth._generate_signature(timestamp, nonce, method, url, None)
        self.assertEqual(actual_signature, expected_signature)

    def test_rest_authenticate(self):
        request = RESTRequest(method=RESTMethod.GET, url="https://api.backpack.exchange/api/v1/orders", is_auth_required=True)
        self.async_run(self.auth.rest_authenticate(request))
        self.assertEqual(request.headers["X-BP-APIKEY"], self.api_key)
        self.assertIn("X-BP-SIGNATURE", request.headers)

    def test_ws_authenticate(self):
        request = WSJSONRequest(payload={}, is_auth_required=True)
        request = self.async_run(self.auth.ws_authenticate(request))
        self.assertEqual(request.payload["op"], "login")
        self.assertEqual(request.payload["args"][0], self.api_key)
