import asyncio
import json
import unittest
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from aioresponses import aioresponses

from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source import (
    BackpackAPIOrderBookDataSource,
)
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage
from hummingbot.core.web_assistant.connections.data_types import WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory


class TestBackpackAPIOrderBookDataSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ev_loop = asyncio.get_event_loop()
        cls.base_asset = "SOL"
        cls.quote_asset = "USDC"
        cls.trading_pair = f"{cls.base_asset}-{cls.quote_asset}"
        cls.exchange_trading_pair = f"{cls.base_asset}_{cls.quote_asset}"

    def setUp(self):
        """Set up test fixtures"""
        self.throttler = AsyncThrottler(rate_limits=CONSTANTS.RATE_LIMITS)
        self.api_factory = WebAssistantsFactory(throttler=self.throttler)
        self.data_source = BackpackAPIOrderBookDataSource(
            trading_pairs=[self.trading_pair],
            throttler=self.throttler,
            api_factory=self.api_factory
        )
        self.log_records = []
        self.data_source.logger().setLevel(1)
        self.data_source.logger().addHandler(self)

    def handle(self, record):
        self.log_records.append(record)

    def async_run_with_timeout(self, coroutine):
        return self.ev_loop.run_until_complete(asyncio.wait_for(coroutine, 30))

    def get_exchange_rules_mock(self) -> List[Dict[str, Any]]:
        """Mock response for trading rules"""
        return [
            {
                "symbol": self.exchange_trading_pair,
                "baseCurrency": self.base_asset,
                "quoteCurrency": self.quote_asset,
                "minOrderSize": "0.01",
                "tickSize": "0.01",
                "stepSize": "0.001",
                "minNotional": "10",
                "status": "ACTIVE"
            }
        ]

    def get_order_book_data_mock(self) -> Dict[str, Any]:
        """Mock response for order book snapshot"""
        return {
            "bids": [
                ["149.50", "10.5"],
                ["149.00", "25.0"],
                ["148.50", "50.0"]
            ],
            "asks": [
                ["150.00", "15.0"],
                ["150.50", "30.0"],
                ["151.00", "45.0"]
            ],
            "lastUpdateId": 123456789,
            "timestamp": 1614550000000
        }

    @aioresponses()
    def test_get_all_markets(self, mock_api):
        """Test fetching all trading pairs"""
        url = f"{CONSTANTS.REST_URL}/{CONSTANTS.MARKETS_PATH_URL}"
        mock_api.get(url, body=json.dumps(self.get_exchange_rules_mock()))
        
        result = self.async_run_with_timeout(
            BackpackAPIOrderBookDataSource.fetch_trading_pairs(
                throttler=self.throttler,
                api_factory=self.api_factory
            )
        )
        
        self.assertEqual(len(result), 1)
        self.assertIn(self.exchange_trading_pair, result)

    @aioresponses()
    def test_get_all_markets_multiple_pairs(self, mock_api):
        """Test fetching multiple trading pairs"""
        markets_data = self.get_exchange_rules_mock()
        # Add another trading pair
        markets_data.append({
            "symbol": "BTC_USDC",
            "baseCurrency": "BTC",
            "quoteCurrency": "USDC",
            "minOrderSize": "0.001",
            "tickSize": "0.01",
            "stepSize": "0.0001",
            "minNotional": "10",
            "status": "ACTIVE"
        })
        
        url = f"{CONSTANTS.REST_URL}/{CONSTANTS.MARKETS_PATH_URL}"
        mock_api.get(url, body=json.dumps(markets_data))
        
        result = self.async_run_with_timeout(
            BackpackAPIOrderBookDataSource.fetch_trading_pairs(
                throttler=self.throttler,
                api_factory=self.api_factory
            )
        )
        
        self.assertEqual(len(result), 2)
        self.assertIn(self.exchange_trading_pair, result)
        self.assertIn("BTC_USDC", result)

    @aioresponses()
    def test_get_order_book_data(self, mock_api):
        """Test fetching order book snapshot"""
        url = f"{CONSTANTS.REST_URL}/{CONSTANTS.DEPTH_PATH_URL}"
        mock_api.get(url, body=json.dumps(self.get_order_book_data_mock()))
        
        result = self.async_run_with_timeout(
            self.data_source.get_order_book_data(self.trading_pair)
        )
        
        # Verify the response structure
        self.assertIn("bids", result)
        self.assertIn("asks", result)
        self.assertIn("lastUpdateId", result)
        self.assertEqual(len(result["bids"]), 3)
        self.assertEqual(len(result["asks"]), 3)
        
        # Verify bid/ask data
        self.assertEqual(result["bids"][0], ["149.50", "10.5"])
        self.assertEqual(result["asks"][0], ["150.00", "15.0"])

    @aioresponses()
    def test_get_new_order_book(self, mock_api):
        """Test creating a new order book from snapshot"""
        url = f"{CONSTANTS.REST_URL}/{CONSTANTS.DEPTH_PATH_URL}"
        mock_api.get(url, body=json.dumps(self.get_order_book_data_mock()))
        
        order_book = self.async_run_with_timeout(
            self.data_source.get_new_order_book(self.trading_pair)
        )
        
        self.assertIsInstance(order_book, OrderBook)
        
        # Check bids
        bids = list(order_book.bid_entries())
        self.assertEqual(len(bids), 3)
        self.assertEqual(float(bids[0].price), 149.50)
        self.assertEqual(float(bids[0].amount), 10.5)
        
        # Check asks
        asks = list(order_book.ask_entries())
        self.assertEqual(len(asks), 3)
        self.assertEqual(float(asks[0].price), 150.00)
        self.assertEqual(float(asks[0].amount), 15.0)

    @patch("aiohttp.ClientSession.ws_connect")
    def test_listen_for_subscriptions(self, ws_connect_mock):
        """Test WebSocket subscription listening"""
        ws_connect_mock.return_value = self.create_websocket_mock()
        
        # Mock WebSocket messages
        messages = [
            {
                "stream": f"depth.{self.exchange_trading_pair}",
                "data": {
                    "e": "depth",
                    "E": 1614550001000000,  # microseconds
                    "s": self.exchange_trading_pair,
                    "U": 123456790,
                    "u": 123456791,
                    "b": [["149.60", "12.0"]],
                    "a": [["149.90", "8.0"]],
                    "T": 1614550001000000
                }
            }
        ]
        
        self.listening_task = self.ev_loop.create_task(
            self.data_source.listen_for_subscriptions()
        )
        
        try:
            for message in messages:
                self.ws_message_queue.put_nowait(json.dumps(message))
            
            # Allow time for message processing
            self.ev_loop.run_until_complete(asyncio.sleep(0.5))
            
            # Check that message was added to queue
            self.assertGreater(self.data_source._message_queue[self.data_source._diff_messages_queue_key].qsize(), 0)
            
        finally:
            self.listening_task.cancel()

    def test_subscribe_message(self):
        """Test WebSocket subscribe message generation"""
        message = self.data_source._get_subscribe_message([f"depth.{self.exchange_trading_pair}"])
        
        self.assertIsInstance(message, WSJSONRequest)
        payload = message.payload
        self.assertEqual(payload["method"], "SUBSCRIBE")
        self.assertEqual(payload["params"], [f"depth.{self.exchange_trading_pair}"])

    def test_unsubscribe_message(self):
        """Test WebSocket unsubscribe message generation"""
        message = self.data_source._get_unsubscribe_message([f"depth.{self.exchange_trading_pair}"])
        
        self.assertIsInstance(message, WSJSONRequest)
        payload = message.payload
        self.assertEqual(payload["method"], "UNSUBSCRIBE")
        self.assertEqual(payload["params"], [f"depth.{self.exchange_trading_pair}"])

    def test_parse_order_book_snapshot(self):
        """Test parsing order book snapshot message"""
        snapshot_data = self.get_order_book_data_mock()
        snapshot_data["trading_pair"] = self.trading_pair
        
        timestamp = 1614550000.0
        message = self.data_source._parse_order_book_snapshot(snapshot_data, timestamp)
        
        self.assertIsInstance(message, OrderBookMessage)
        self.assertEqual(message.trading_pair, self.trading_pair)
        self.assertEqual(message.update_id, 123456789)
        self.assertEqual(message.timestamp, timestamp)
        
        # Check bids and asks are properly sorted
        self.assertEqual(len(message.bids), 3)
        self.assertEqual(len(message.asks), 3)
        self.assertEqual(message.bids[0][0], 149.50)  # Highest bid first
        self.assertEqual(message.asks[0][0], 150.00)  # Lowest ask first

    def test_parse_order_book_diff(self):
        """Test parsing order book diff message"""
        diff_data = {
            "e": "depth",
            "E": 1614550001000000,  # microseconds
            "s": self.exchange_trading_pair,
            "U": 123456790,
            "u": 123456791,
            "b": [["149.60", "12.0"], ["148.00", "0.0"]],  # New bid and removed bid
            "a": [["149.90", "8.0"], ["152.00", "0.0"]],   # New ask and removed ask
            "T": 1614550001000000
        }
        
        message = self.data_source._parse_diff_message(diff_data, 1614550001.0)
        
        self.assertIsInstance(message, OrderBookMessage)
        self.assertEqual(message.trading_pair, self.trading_pair)
        self.assertEqual(message.update_id, 123456791)
        self.assertEqual(message.first_update_id, 123456790)
        
        # Check that zero quantity entries are included (for removal)
        bid_dict = {price: amount for price, amount in message.bids}
        ask_dict = {price: amount for price, amount in message.asks}
        self.assertEqual(bid_dict[148.00], 0.0)
        self.assertEqual(ask_dict[152.00], 0.0)

    async def test_listen_for_order_book_diffs(self):
        """Test listening for order book diff updates"""
        # Add a diff message to the queue
        diff_msg = OrderBookMessage(
            message_type=OrderBookMessage.Type.DIFF,
            content={
                "trading_pair": self.trading_pair,
                "update_id": 123456791,
                "first_update_id": 123456790,
                "bids": [(149.60, 12.0)],
                "asks": [(149.90, 8.0)]
            },
            timestamp=1614550001.0
        )
        
        self.data_source._message_queue[self.data_source._diff_messages_queue_key].put_nowait(diff_msg)
        
        # Listen for the message
        async for message in self.data_source.listen_for_order_book_diffs(
            ev_loop=self.ev_loop,
            output=asyncio.Queue()
        ):
            self.assertEqual(message, diff_msg)
            break

    async def test_listen_for_order_book_snapshots(self):
        """Test listening for order book snapshots"""
        # Add a snapshot message to the queue
        snapshot_msg = OrderBookMessage(
            message_type=OrderBookMessage.Type.SNAPSHOT,
            content={
                "trading_pair": self.trading_pair,
                "update_id": 123456789,
                "bids": [(149.50, 10.5), (149.00, 25.0)],
                "asks": [(150.00, 15.0), (150.50, 30.0)]
            },
            timestamp=1614550000.0
        )
        
        self.data_source._message_queue[self.data_source._snapshot_messages_queue_key].put_nowait(snapshot_msg)
        
        # Listen for the message
        async for message in self.data_source.listen_for_order_book_snapshots(
            ev_loop=self.ev_loop,
            output=asyncio.Queue()
        ):
            self.assertEqual(message, snapshot_msg)
            break

    def create_websocket_mock(self):
        """Create a mock WebSocket connection"""
        ws = AsyncMock()
        self.ws_message_queue = asyncio.Queue()
        
        async def receive_json():
            msg = await self.ws_message_queue.get()
            return json.loads(msg)
        
        async def send_json(data):
            pass
        
        ws.receive_json = receive_json
        ws.send_json = send_json
        ws.close = AsyncMock()
        
        return ws

    @patch("aiohttp.ClientSession.ws_connect")
    async def test_websocket_reconnection_with_exponential_backoff(self, ws_connect_mock):
        """Test WebSocket reconnection with exponential backoff"""
        # Create a mock that fails first 3 times, then succeeds
        connection_attempts = []
        
        async def mock_connect(*args, **kwargs):
            connection_attempts.append(time.time())
            attempt_num = len(connection_attempts)
            
            if attempt_num <= 3:
                raise ConnectionError(f"Connection attempt {attempt_num} failed")
            
            # Return successful connection
            return self.create_websocket_mock()
        
        ws_connect_mock.side_effect = mock_connect
        
        # Start listening (in background)
        listen_task = asyncio.create_task(self.data_source.listen_for_subscriptions())
        
        try:
            # Wait for reconnection attempts
            await asyncio.sleep(10)
            
            # Verify exponential backoff timing
            self.assertGreaterEqual(len(connection_attempts), 4)
            
            # Check that delays increase exponentially (allowing some variance)
            if len(connection_attempts) >= 3:
                delay1 = connection_attempts[1] - connection_attempts[0]
                delay2 = connection_attempts[2] - connection_attempts[1]
                
                # Second delay should be approximately double the first
                self.assertGreater(delay2, delay1 * 1.5)
                
        finally:
            listen_task.cancel()
            try:
                await listen_task
            except asyncio.CancelledError:
                pass

    @patch("aiohttp.ClientSession.ws_connect")
    async def test_connection_health_monitoring(self, ws_connect_mock):
        """Test connection health monitoring detects stale connections"""
        ws_mock = self.create_websocket_mock()
        ws_connect_mock.return_value = ws_mock
        
        # Reduce timeouts for faster testing
        self.data_source._connection_timeout = 2.0  # 2 seconds
        self.data_source._health_check_interval = 0.5  # 0.5 seconds
        
        listen_task = asyncio.create_task(self.data_source.listen_for_subscriptions())
        
        try:
            # Wait for connection to establish
            await asyncio.sleep(0.5)
            
            # Send initial message to establish connection
            test_message = {
                "stream": f"depth.{self.exchange_trading_pair}",
                "data": {
                    "e": "depth",
                    "E": int(time.time() * 1e6),
                    "s": self.exchange_trading_pair,
                    "U": 100,
                    "u": 101,
                    "b": [],
                    "a": []
                }
            }
            self.ws_message_queue.put_nowait(json.dumps(test_message))
            
            # Wait a bit, connection should still be healthy
            await asyncio.sleep(1.0)
            
            # Verify connection is still active
            self.assertIsNotNone(self.data_source._ws_assistant)
            
            # Now wait without sending messages to trigger health check failure
            await asyncio.sleep(3.0)
            
            # Connection should have been detected as stale and reconnection attempted
            # Check logs for stale connection message
            stale_logs = [log for log in self.log_records if "stale" in log.getMessage()]
            self.assertGreater(len(stale_logs), 0)
            
        finally:
            listen_task.cancel()
            try:
                await listen_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    unittest.main()