import asyncio
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
        return asyncio.get_event_loop().run_until_complete(asyncio.wait_for(coroutine, 1))

    def test_generate_signature(self):
        expected = self.auth._generate_signature("1692693725000", "1692693725000", RESTMethod.GET, "/api/v1/orders", None)
        self.assertEqual(expected, "714be7871dc2102c389f6123c4c1f51889586223d8ae13db262c63c832ee1902")

    def test_rest_authenticate(self):
        request = RESTRequest(method=RESTMethod.GET, url="https://api.backpack.exchange/api/v1/orders", is_auth_required=True)
        self.async_run(self.auth.rest_authenticate(request))
        self.assertEqual(request.headers["X-BP-APIKEY"], self.api_key)
        self.assertIn("X-BP-SIGNATURE", request.headers)

    def test_ws_authenticate(self):
        request = WSJSONRequest(payload={}, is_auth_required=True)
        result = self.async_run(self.auth.ws_authenticate(request))
        self.assertEqual(result["op"], "login")
        self.assertEqual(result["args"][0], self.api_key)

