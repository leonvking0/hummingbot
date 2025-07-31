import asyncio
import time
import unittest
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

from aioresponses import aioresponses

from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.api_throttler.data_types import RateLimit
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory


class TestBackpackRateLimits(unittest.TestCase):
    """Test rate limiting functionality for Backpack Exchange connector"""
    
    @classmethod
    def setUpClass(cls):
        cls.ev_loop = asyncio.get_event_loop()
    
    def setUp(self):
        """Set up test fixtures"""
        self.throttler = AsyncThrottler(rate_limits=CONSTANTS.RATE_LIMITS)
        self.api_factory = WebAssistantsFactory(throttler=self.throttler)
        self.request_times: List[float] = []
        
    def async_run_with_timeout(self, coroutine):
        return self.ev_loop.run_until_complete(asyncio.wait_for(coroutine, 30))
    
    @aioresponses()
    async def test_concurrent_requests_within_limit(self, mock_api):
        """Test that concurrent requests respect rate limits"""
        # Mock responses for multiple endpoints
        base_url = CONSTANTS.REST_URL
        endpoints = [
            CONSTANTS.MARKETS_PATH_URL,
            CONSTANTS.TICKER_PATH_URL,
            CONSTANTS.DEPTH_PATH_URL,
        ]
        
        # Set up mock responses
        for endpoint in endpoints:
            url = f"{base_url}/{endpoint}"
            mock_api.get(url, payload={"status": "ok"}, repeat=True)
        
        # Create tasks for concurrent requests (3 requests per endpoint = 9 total)
        tasks = []
        for endpoint in endpoints:
            for i in range(3):
                task = self._make_throttled_request(endpoint)
                tasks.append(task)
        
        # Execute all requests concurrently
        start_time = time.time()
        await asyncio.gather(*tasks)
        end_time = time.time()
        
        # Verify timing - 9 requests at 10/second should complete in ~1 second
        total_time = end_time - start_time
        self.assertGreater(total_time, 0.8)  # Should take at least 0.8 seconds
        self.assertLess(total_time, 2.0)  # But not more than 2 seconds
        
        # Verify request spacing
        self._verify_rate_limit_compliance(self.request_times, limit=10, interval=1)
    
    @aioresponses()
    async def test_burst_requests_throttled(self, mock_api):
        """Test that burst requests are properly throttled"""
        # Mock the endpoint
        url = f"{CONSTANTS.REST_URL}/{CONSTANTS.TICKER_PATH_URL}"
        mock_api.get(url, payload={"status": "ok"}, repeat=True)
        
        # Attempt to make 20 rapid requests (exceeds 10/second limit)
        tasks = []
        for i in range(20):
            task = self._make_throttled_request(CONSTANTS.TICKER_PATH_URL)
            tasks.append(task)
        
        # Execute burst requests
        start_time = time.time()
        await asyncio.gather(*tasks)
        end_time = time.time()
        
        # Should take ~2 seconds for 20 requests at 10/second
        total_time = end_time - start_time
        self.assertGreater(total_time, 1.8)
        self.assertLess(total_time, 3.0)
        
        # Verify no more than 10 requests per second
        self._verify_rate_limit_compliance(self.request_times, limit=10, interval=1)
    
    @aioresponses()
    async def test_rate_limit_recovery(self, mock_api):
        """Test recovery after hitting rate limits"""
        # Mock the endpoint
        url = f"{CONSTANTS.REST_URL}/{CONSTANTS.ORDER_PATH_URL}"
        mock_api.post(url, payload={"status": "ok"}, repeat=True)
        
        # First burst - 10 requests
        first_burst = []
        for i in range(10):
            task = self._make_throttled_request(
                CONSTANTS.ORDER_PATH_URL,
                method=RESTMethod.POST
            )
            first_burst.append(task)
        
        first_start = time.time()
        await asyncio.gather(*first_burst)
        first_end = time.time()
        
        # Wait for rate limit window to reset
        await asyncio.sleep(1.1)
        
        # Second burst - should proceed without delay
        second_burst = []
        for i in range(10):
            task = self._make_throttled_request(
                CONSTANTS.ORDER_PATH_URL,
                method=RESTMethod.POST
            )
            second_burst.append(task)
        
        second_start = time.time()
        await asyncio.gather(*second_burst)
        second_end = time.time()
        
        # Both bursts should complete quickly (under 0.5 seconds each)
        first_duration = first_end - first_start
        second_duration = second_end - second_start
        
        self.assertLess(first_duration, 0.5)
        self.assertLess(second_duration, 0.5)
    
    @aioresponses()
    async def test_endpoint_specific_limits(self, mock_api):
        """Test that rate limits are applied per endpoint"""
        # Mock different endpoints
        markets_url = f"{CONSTANTS.REST_URL}/{CONSTANTS.MARKETS_PATH_URL}"
        ticker_url = f"{CONSTANTS.REST_URL}/{CONSTANTS.TICKER_PATH_URL}"
        
        mock_api.get(markets_url, payload={"markets": []}, repeat=True)
        mock_api.get(ticker_url, payload={"ticker": {}}, repeat=True)
        
        # Track requests per endpoint
        markets_times = []
        ticker_times = []
        
        # Make interleaved requests to different endpoints
        tasks = []
        for i in range(5):
            # Markets request
            task = self._make_throttled_request(
                CONSTANTS.MARKETS_PATH_URL,
                track_times=markets_times
            )
            tasks.append(task)
            
            # Ticker request
            task = self._make_throttled_request(
                CONSTANTS.TICKER_PATH_URL,
                track_times=ticker_times
            )
            tasks.append(task)
        
        # Execute all requests
        await asyncio.gather(*tasks)
        
        # Verify each endpoint respects its own rate limit
        self._verify_rate_limit_compliance(markets_times, limit=10, interval=1)
        self._verify_rate_limit_compliance(ticker_times, limit=10, interval=1)
    
    async def test_rate_limit_configuration(self):
        """Test that rate limits are properly configured"""
        # Verify all endpoints have rate limits defined
        limit_ids = [limit.limit_id for limit in CONSTANTS.RATE_LIMITS]
        
        expected_endpoints = [
            CONSTANTS.MARKETS_PATH_URL,
            CONSTANTS.TICKER_PATH_URL,
            CONSTANTS.DEPTH_PATH_URL,
            CONSTANTS.TRADES_PATH_URL,
            CONSTANTS.ORDER_PATH_URL,
            CONSTANTS.ORDERS_PATH_URL,
        ]
        
        for endpoint in expected_endpoints:
            self.assertIn(endpoint, limit_ids, f"Missing rate limit for {endpoint}")
        
        # Verify all limits are reasonable (between 1 and 100 per second)
        for limit in CONSTANTS.RATE_LIMITS:
            rate_per_second = limit.limit / limit.time_interval
            self.assertGreaterEqual(rate_per_second, 1)
            self.assertLessEqual(rate_per_second, 100)
    
    async def test_throttler_shared_across_requests(self):
        """Test that the same throttler instance is used for all requests"""
        # Create a custom throttler with very restrictive limits
        restrictive_limits = [
            RateLimit(
                limit_id=CONSTANTS.TICKER_PATH_URL,
                limit=2,  # Only 2 requests per second
                time_interval=1
            )
        ]
        restrictive_throttler = AsyncThrottler(rate_limits=restrictive_limits)
        
        # Use the restrictive throttler
        self.api_factory._throttler = restrictive_throttler
        
        with aioresponses() as mock_api:
            url = f"{CONSTANTS.REST_URL}/{CONSTANTS.TICKER_PATH_URL}"
            mock_api.get(url, payload={"status": "ok"}, repeat=True)
            
            # Make 4 requests - should take ~2 seconds with 2/second limit
            start_time = time.time()
            tasks = []
            for i in range(4):
                task = self._make_throttled_request(
                    CONSTANTS.TICKER_PATH_URL,
                    throttler=restrictive_throttler
                )
                tasks.append(task)
            
            await asyncio.gather(*tasks)
            end_time = time.time()
            
            # Should take at least 1.5 seconds for 4 requests at 2/second
            duration = end_time - start_time
            self.assertGreater(duration, 1.5)
    
    async def _make_throttled_request(
        self,
        endpoint: str,
        method: RESTMethod = RESTMethod.GET,
        track_times: List[float] = None,
        throttler: AsyncThrottler = None
    ):
        """Make a throttled request and track timing"""
        if track_times is None:
            track_times = self.request_times
        
        throttler = throttler or self.throttler
        rest_assistant = await self.api_factory.get_rest_assistant()
        
        url = f"{CONSTANTS.REST_URL}/{endpoint}"
        
        # Execute request through throttler
        async with throttler.execute_task(endpoint):
            track_times.append(time.time())
            # Simulate request execution
            await asyncio.sleep(0.01)
    
    def _verify_rate_limit_compliance(
        self,
        request_times: List[float],
        limit: int,
        interval: float
    ):
        """Verify that requests comply with rate limits"""
        if len(request_times) <= 1:
            return
        
        # Check that no more than 'limit' requests occur within 'interval' seconds
        for i in range(len(request_times)):
            window_start = request_times[i]
            window_end = window_start + interval
            
            # Count requests in this window
            requests_in_window = 0
            for req_time in request_times[i:]:
                if req_time <= window_end:
                    requests_in_window += 1
                else:
                    break
            
            # Allow 1 extra request for timing variance
            self.assertLessEqual(
                requests_in_window,
                limit + 1,
                f"Too many requests ({requests_in_window}) in {interval}s window"
            )


if __name__ == "__main__":
    unittest.main()