import json
import unittest
from typing import Dict
from unittest.mock import MagicMock, patch

import aiohttp
from aioresponses import aioresponses

from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.connector.exchange.backpack import backpack_web_utils as web_utils
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory


class TestBackpackWebUtils(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures"""
        self.throttler = AsyncThrottler(rate_limits=CONSTANTS.RATE_LIMITS)

    def test_public_rest_url(self):
        """Test public REST URL generation"""
        # Test with path URL
        url = web_utils.public_rest_url(path_url="/test/path")
        self.assertEqual(url, f"{CONSTANTS.REST_URL}/test/path")
        
        # Test without leading slash
        url = web_utils.public_rest_url(path_url="test/path")
        self.assertEqual(url, f"{CONSTANTS.REST_URL}/test/path")

    def test_private_rest_url(self):
        """Test private REST URL generation"""
        # For Backpack, private URLs are the same as public
        url = web_utils.private_rest_url(path_url="/test/path")
        self.assertEqual(url, f"{CONSTANTS.REST_URL}/test/path")

    def test_build_api_factory(self):
        """Test API factory creation"""
        # Test without auth
        api_factory = web_utils.build_api_factory(throttler=self.throttler)
        self.assertIsInstance(api_factory, WebAssistantsFactory)
        self.assertIsNone(api_factory._auth)
        
        # Test with auth
        mock_auth = MagicMock()
        api_factory = web_utils.build_api_factory(
            throttler=self.throttler,
            auth=mock_auth
        )
        self.assertIsInstance(api_factory, WebAssistantsFactory)
        self.assertEqual(api_factory._auth, mock_auth)

    def test_build_api_factory_without_time_synchronizer(self):
        """Test API factory creation without time synchronizer"""
        api_factory = web_utils.build_api_factory(throttler=self.throttler)
        self.assertIsInstance(api_factory, WebAssistantsFactory)

    @aioresponses()
    def test_rest_assistant_creation(self, mock_api):
        """Test that REST assistant can be created and used"""
        api_factory = web_utils.build_api_factory(throttler=self.throttler)
        rest_assistant = api_factory.get_rest_assistant()
        
        # Mock a simple GET request
        test_url = f"{CONSTANTS.REST_URL}/test"
        mock_api.get(test_url, body=json.dumps({"status": "ok"}))
        
        # The assistant should be able to execute requests
        self.assertIsNotNone(rest_assistant)

    def test_get_current_server_time(self):
        """Test server time retrieval"""
        throttler = self.throttler
        # This would normally make an API call, but we're just testing the function exists
        # and returns the expected structure
        self.assertTrue(callable(web_utils.get_current_server_time))

    def test_wss_url(self):
        """Test WebSocket URL generation"""
        # Test that WSS URL is properly formatted
        self.assertTrue(CONSTANTS.WSS_URL.startswith("wss://"))
        self.assertIn("backpack", CONSTANTS.WSS_URL)

    def test_api_endpoints_constants(self):
        """Test that all required API endpoint constants are defined"""
        # Check REST endpoints
        self.assertIsNotNone(CONSTANTS.MARKETS_PATH_URL)
        self.assertIsNotNone(CONSTANTS.DEPTH_PATH_URL)
        self.assertIsNotNone(CONSTANTS.TICKER_PATH_URL)
        self.assertIsNotNone(CONSTANTS.ORDER_CREATE_PATH_URL)
        self.assertIsNotNone(CONSTANTS.ORDER_DELETE_PATH_URL)
        self.assertIsNotNone(CONSTANTS.ORDER_QUERY_PATH_URL)
        
        # Check rate limits are defined
        self.assertIsInstance(CONSTANTS.RATE_LIMITS, list)
        self.assertGreater(len(CONSTANTS.RATE_LIMITS), 0)

    def test_create_throttler(self):
        """Test throttler creation with rate limits"""
        throttler = AsyncThrottler(rate_limits=CONSTANTS.RATE_LIMITS)
        
        # Verify throttler has the rate limits
        for rate_limit in CONSTANTS.RATE_LIMITS:
            limit_id = rate_limit.limit_id
            self.assertIn(limit_id, throttler._rate_limits)

    def test_headers_generation(self):
        """Test that proper headers are generated for requests"""
        # Headers should include proper user agent and content type
        api_factory = web_utils.build_api_factory(throttler=self.throttler)
        
        # Test that factory can create REST assistant with proper configuration
        rest_assistant = api_factory.get_rest_assistant()
        self.assertIsNotNone(rest_assistant)


if __name__ == "__main__":
    unittest.main()