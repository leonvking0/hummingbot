"""
Tests for Backpack Exchange WebSocket reliability improvements.
Tests cover error handling, reconnection, heartbeat, and state management.
"""

import asyncio
import json
import logging
import time
import unittest
from decimal import Decimal
from typing import Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from aioresponses import aioresponses

from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source import (
    BackpackAPIOrderBookDataSource
)
from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.order_book_row import OrderBookRow
from hummingbot.core.network_iterator import NetworkStatus
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant


class TestBackpackWebSocketReliability(unittest.TestCase):
    """Test suite for WebSocket reliability improvements"""
    
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        # Fix deprecation warning by using new_event_loop if no loop exists
        try:
            cls.ev_loop = asyncio.get_running_loop()
        except RuntimeError:
            cls.ev_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(cls.ev_loop)
        cls.base_asset = "SOL"
        cls.quote_asset = "USDC"
        cls.trading_pair = f"{cls.base_asset}-{cls.quote_asset}"
        cls.exchange_symbol = f"{cls.base_asset}_{cls.quote_asset}"
        
    def setUp(self) -> None:
        super().setUp()
        self.log_records = []
        self.async_tasks = []
        
        # Set up as a proper log handler with required attributes
        self.level = logging.DEBUG  # Required attribute for log handlers
        
        self.throttler = AsyncThrottler(rate_limits=CONSTANTS.RATE_LIMITS)
        self.data_source = BackpackAPIOrderBookDataSource(
            trading_pairs=[self.trading_pair],
            throttler=self.throttler
        )
        self.data_source.logger().setLevel(logging.DEBUG)
        self.data_source.logger().addHandler(self)
        
        self.mocking_assistant = NetworkMocking()
        
    def tearDown(self) -> None:
        for task in self.async_tasks:
            task.cancel()
        super().tearDown()
        
    def handle(self, record):
        """Capture log records for verification"""
        self.log_records.append(record)
        
    def _is_logged(self, log_level: str, message: str) -> bool:
        """Check if a specific log message was recorded"""
        return any(
            record.levelname == log_level and message in record.getMessage()
            for record in self.log_records
        )
        
    def async_run_with_timeout(self, coroutine, timeout: float = 1):
        ret = self.ev_loop.run_until_complete(asyncio.wait_for(coroutine, timeout))
        return ret
        
    # Task 3.1: Error Handling Tests
    
    def test_process_websocket_messages_handles_malformed_json(self):
        """Test that WebSocket continues processing after receiving malformed JSON"""
        ws_assistant = AsyncMock()
        
        # Create a sequence of messages: malformed, valid, malformed, valid
        messages = [
            MagicMock(data="malformed json {"),  # Invalid JSON
            MagicMock(data={  # Valid depth message
                "stream": f"depth.{self.exchange_symbol}",
                "data": {
                    "asks": [["10.5", "100"]],
                    "bids": [["10.4", "150"]],
                    "E": int(time.time() * 1e6)
                }
            }),
            MagicMock(data={"stream": "incomplete"}),  # Missing data field
            MagicMock(data={  # Valid trade message
                "stream": f"trade.{self.exchange_symbol}",
                "data": {
                    "p": "10.45",
                    "q": "50",
                    "E": int(time.time() * 1e6),
                    "m": False
                }
            })
        ]
        
        async def mock_iter():
            for msg in messages:
                yield msg
                
        ws_assistant.iter_messages = lambda: mock_iter()
        
        # Process messages
        with patch.object(self.data_source, "_parse_order_book_diff_message") as mock_parse_depth:
            with patch.object(self.data_source, "_parse_trade_message") as mock_parse_trade:
                # Set up message queues
                self.data_source._message_queue = {
                    self.data_source._diff_messages_queue_key: asyncio.Queue(),
                    self.data_source._trade_messages_queue_key: asyncio.Queue()
                }
                
                self.async_run_with_timeout(
                    self.data_source._process_websocket_messages(ws_assistant),
                    timeout=0.5
                )
                
                # Verify valid messages were processed
                self.assertEqual(mock_parse_depth.call_count, 1)
                self.assertEqual(mock_parse_trade.call_count, 1)
                
                # Verify warnings were logged for malformed messages
                self.assertTrue(self._is_logged("WARNING", "non-dict") or self._is_logged("WARNING", "missing"))
                
    def test_process_websocket_messages_handles_missing_fields(self):
        """Test handling of messages with missing required fields"""
        ws_assistant = AsyncMock()
        
        messages = [
            MagicMock(data={  # Missing stream field
                "data": {"asks": [], "bids": []}
            }),
            MagicMock(data={  # Missing data field
                "stream": f"depth.{self.exchange_symbol}"
            }),
            MagicMock(data={  # Valid message
                "stream": f"depth.{self.exchange_symbol}",
                "data": {
                    "asks": [["10.5", "100"]],
                    "bids": [["10.4", "150"]],
                    "E": int(time.time() * 1e6)
                }
            })
        ]
        
        async def mock_iter():
            for msg in messages:
                yield msg
                
        ws_assistant.iter_messages = lambda: mock_iter()
        
        # Track how many valid messages are processed
        processed_count = 0
        original_parse = self.data_source._parse_order_book_diff_message
        
        async def counting_parse(*args, **kwargs):
            nonlocal processed_count
            processed_count += 1
            return await original_parse(*args, **kwargs)
        
        with patch.object(self.data_source, "_parse_order_book_diff_message", counting_parse):
            # Set up message queues
            self.data_source._message_queue = {
                self.data_source._diff_messages_queue_key: asyncio.Queue(),
                self.data_source._trade_messages_queue_key: asyncio.Queue()
            }
            
            self.async_run_with_timeout(
                self.data_source._process_websocket_messages(ws_assistant),
                timeout=0.5
            )
            
            # Only the valid message should be processed
            self.assertEqual(processed_count, 1)
            
            # Check that warnings were logged for invalid messages
            self.assertTrue(
                self._is_logged("WARNING", "missing") or
                self._is_logged("WARNING", "Missing")
            )
            
    def test_process_websocket_messages_handles_invalid_data_types(self):
        """Test handling of messages with invalid data types"""
        ws_assistant = AsyncMock()
        
        messages = [
            MagicMock(data={
                "stream": f"depth.{self.exchange_symbol}",
                "data": {
                    "asks": "not_a_list",  # Invalid type - will cause iteration error
                    "bids": [["10.4", "150"]],
                    "E": int(time.time() * 1e6)
                }
            }),
            MagicMock(data={
                "stream": f"trade.{self.exchange_symbol}",
                "data": {
                    "p": None,  # Invalid price - will cause Decimal conversion error
                    "q": "50",
                    "E": int(time.time() * 1e6),
                    "m": False
                }
            })
        ]
        
        async def mock_iter():
            for msg in messages:
                yield msg
                
        ws_assistant.iter_messages = lambda: mock_iter()
        
        # Set up message queues
        self.data_source._message_queue = {
            self.data_source._diff_messages_queue_key: asyncio.Queue(),
            self.data_source._trade_messages_queue_key: asyncio.Queue()
        }
        
        # Should handle errors gracefully
        self.async_run_with_timeout(
            self.data_source._process_websocket_messages(ws_assistant),
            timeout=0.5
        )
        
        # Check that errors were logged (these will be caught in the parse methods)
        # The errors happen when utils.parse_order_book_diff tries to iterate "not_a_list"
        # or when Decimal(None) is attempted
        self.assertTrue(
            self._is_logged("ERROR", "Error parsing") or 
            self._is_logged("ERROR", "Error processing")
        )
        
    # Task 3.2: Timestamp Conversion Tests
    
    def test_timestamp_conversion_consistency(self):
        """Test that timestamps are consistently converted from microseconds"""
        # Test with provided timestamp (microseconds)
        provided_timestamp_us = 1234567890123456  # microseconds
        
        # Test through the parse_trade_message_data method which we can access
        trade_data = {
            "p": "10.5",
            "q": "100",
            "E": provided_timestamp_us,
            "m": False
        }
        
        # Parse message and check timestamp conversion
        parsed_msg = self.data_source._parse_trade_message_data(
            trade_data,
            self.trading_pair
        )
        
        # Timestamp should be in seconds (microseconds / 1e6)
        expected_timestamp_s = provided_timestamp_us / 1e6
        self.assertAlmostEqual(parsed_msg.timestamp, expected_timestamp_s, places=6)
        
    def test_timestamp_fallback_consistency(self):
        """Test fallback timestamp generation when not provided"""
        # Test with missing timestamp (should use current time)
        trade_data = {
            "p": "10.5",
            "q": "100",
            "m": False
            # No "E" field
        }
        
        with patch("time.time", return_value=1234567890.123456):
            parsed_msg = self.data_source._parse_trade_message_data(
                trade_data,
                self.trading_pair
            )
            
            # Should use current time as fallback
            self.assertAlmostEqual(parsed_msg.timestamp, 1234567890.123456, places=6)
            
    def test_timestamp_ordering_preservation(self):
        """Test that timestamp ordering is preserved through conversions"""
        timestamps_us = [
            1234567890000000,
            1234567891000000,
            1234567892000000
        ]
        
        parsed_timestamps = []
        for ts in timestamps_us:
            trade_data = {
                "p": "10.5",
                "q": "100",
                "E": ts,
                "m": False
            }
            parsed_msg = self.data_source._parse_trade_message_data(
                trade_data,
                self.trading_pair
            )
            parsed_timestamps.append(parsed_msg.timestamp)
            
        # Verify ordering is preserved
        for i in range(len(parsed_timestamps) - 1):
            self.assertLess(parsed_timestamps[i], parsed_timestamps[i + 1])
            
    # Task 3.3: Auto-Reconnection Tests
    
    @patch("hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source.BackpackAPIOrderBookDataSource._connected_websocket_assistant")
    @patch("hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source.BackpackAPIOrderBookDataSource._subscribe_channels")
    async def test_websocket_auto_reconnection_with_exponential_backoff(self, mock_subscribe_channels, mock_connected_ws):
        """Test WebSocket reconnection with exponential backoff"""
        # Simulate connection failures followed by success
        mock_connected_ws.side_effect = [
            Exception("Connection failed"),
            Exception("Connection failed"),
            Exception("Connection failed"),
            AsyncMock()  # Success on 4th attempt
        ]
        mock_subscribe_channels.return_value = None
        
        ws_assistant = AsyncMock()
        
        # Track sleep calls to verify exponential backoff
        sleep_times = []
        async def mock_sleep(seconds):
            sleep_times.append(seconds)
            
        with patch("asyncio.sleep", new=mock_sleep):
            await self.data_source._on_order_stream_interruption(ws_assistant)
            
        # Verify exponential backoff pattern (1s, 2s, 4s)
        self.assertEqual(len(sleep_times), 3)
        self.assertEqual(sleep_times[0], 1)
        self.assertEqual(sleep_times[1], 2)
        self.assertEqual(sleep_times[2], 4)
        
        # Verify successful reconnection
        self.assertEqual(mock_connected_ws.call_count, 4)
        self.assertTrue(self._is_logged("INFO", "Successfully reconnected"))
        
    @patch("hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source.BackpackAPIOrderBookDataSource._connected_websocket_assistant")
    async def test_websocket_max_reconnection_attempts(self, mock_connected_ws):
        """Test that reconnection stops after max attempts"""
        # All attempts fail
        mock_connected_ws.side_effect = Exception("Connection failed")
        
        ws_assistant = AsyncMock()
        
        with patch("asyncio.sleep", new=AsyncMock()):
            await self.data_source._on_order_stream_interruption(ws_assistant)
            
        # Should attempt MAX_RECONNECT_ATTEMPTS times
        self.assertEqual(mock_connected_ws.call_count, self.data_source.MAX_RECONNECT_ATTEMPTS)
        self.assertTrue(self._is_logged("CRITICAL", "Max reconnection attempts reached"))
        
    @patch("hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source.BackpackAPIOrderBookDataSource._connected_websocket_assistant")
    async def test_websocket_reconnection_backoff_cap(self, mock_connected_ws):
        """Test that exponential backoff is capped at max value"""
        # Simulate many failures to test backoff cap
        mock_connected_ws.side_effect = [Exception("Failed")] * 10
        
        ws_assistant = AsyncMock()
        sleep_times = []
        
        async def mock_sleep(seconds):
            sleep_times.append(seconds)
            
        with patch("asyncio.sleep", new=mock_sleep):
            await self.data_source._on_order_stream_interruption(ws_assistant)
            
        # Verify backoff is capped at 30 seconds
        max_sleep = max(sleep_times)
        self.assertLessEqual(max_sleep, 30)
        
    # Task 3.4: Heartbeat Tests
    
    async def test_websocket_heartbeat_sending(self):
        """Test that heartbeat messages are sent periodically"""
        ws_assistant = AsyncMock()
        sent_messages = []
        
        async def mock_send(message):
            sent_messages.append(message)
            
        ws_assistant.send = mock_send
        self.data_source._ws_assistant = ws_assistant
        
        # Run heartbeat for a short time
        heartbeat_task = asyncio.create_task(
            self.data_source._send_heartbeat(ws_assistant)
        )
        
        await asyncio.sleep(0.1)  # Let it send at least one heartbeat
        heartbeat_task.cancel()
        
        # Verify heartbeat was sent
        self.assertTrue(any(msg.get("op") == "ping" for msg in sent_messages))
        
    async def test_websocket_heartbeat_timeout_triggers_reconnection(self):
        """Test that heartbeat timeout triggers reconnection"""
        self.data_source._ws_assistant = AsyncMock()
        self.data_source._last_heartbeat = time.time() - (CONSTANTS.WS_HEARTBEAT_TIMEOUT + 10)
        
        with patch.object(self.data_source, "_on_order_stream_interruption") as mock_reconnect:
            monitor_task = asyncio.create_task(
                self.data_source._monitor_heartbeat()
            )
            
            await asyncio.sleep(0.1)
            monitor_task.cancel()
            
            # Verify reconnection was triggered
            mock_reconnect.assert_called_once()
            
    async def test_websocket_heartbeat_error_handling(self):
        """Test heartbeat error handling"""
        ws_assistant = AsyncMock()
        ws_assistant.send = AsyncMock(side_effect=Exception("Send failed"))
        self.data_source._ws_assistant = ws_assistant
        
        with patch.object(self.data_source, "_on_order_stream_interruption") as mock_reconnect:
            await self.data_source._send_heartbeat(ws_assistant)
            
            # Should trigger reconnection on send failure
            mock_reconnect.assert_called_once()
            self.assertTrue(self._is_logged("ERROR", "Error sending heartbeat"))
            
    # Task 3.5: Message Queue Overflow Tests
    
    async def test_message_queue_overflow_handling(self):
        """Test handling of message queue overflow"""
        # Create a small queue that will overflow
        small_queue = asyncio.Queue(maxsize=2)
        
        # Fill the queue
        await small_queue.put("message1")
        await small_queue.put("message2")
        
        # Try to add more messages
        overflow_msg = OrderBookMessage(
            message_type=OrderBookMessageType.DIFF,
            content={"test": "data"},
            timestamp=time.time()
        )
        
        # Should handle overflow gracefully
        try:
            small_queue.put_nowait(overflow_msg)
            self.fail("Expected QueueFull exception")
        except asyncio.QueueFull:
            # This is expected - now verify it's handled properly
            pass
            
        # Verify dropped message is logged
        with patch.object(self.data_source, "logger") as mock_logger:
            self.data_source._handle_queue_overflow(
                small_queue,
                overflow_msg,
                self.trading_pair
            )
            mock_logger.warning.assert_called_with(
                f"Message queue full for {self.trading_pair}, dropping message"
            )
            
    async def test_message_queue_overflow_triggers_reconnection(self):
        """Test that excessive dropped messages trigger reconnection"""
        self.data_source._dropped_messages_count = self.data_source.MAX_DROPPED_MESSAGES + 1
        
        with patch.object(self.data_source, "_on_order_stream_interruption") as mock_reconnect:
            await self.data_source._check_dropped_messages()
            
            # Should trigger reconnection
            mock_reconnect.assert_called_once()
            self.assertTrue(self._is_logged("ERROR", "Too many dropped messages"))
            
    # Task 3.6: State Management Tests
    
    def test_websocket_state_transitions(self):
        """Test WebSocket state transitions"""
        from hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source import WebSocketState
            
        # Test valid transitions
        valid_transitions = [
            (WebSocketState.DISCONNECTED, WebSocketState.CONNECTING),
            (WebSocketState.CONNECTING, WebSocketState.CONNECTED),
            (WebSocketState.CONNECTED, WebSocketState.DISCONNECTING),
            (WebSocketState.DISCONNECTING, WebSocketState.DISCONNECTED),
            (WebSocketState.CONNECTED, WebSocketState.RECONNECTING),
            (WebSocketState.RECONNECTING, WebSocketState.CONNECTED),
        ]
        
        for from_state, to_state in valid_transitions:
            self.data_source._ws_state = from_state
            self.data_source._set_ws_state(to_state)
            self.assertEqual(self.data_source._ws_state, to_state)
            
    def test_websocket_operations_blocked_in_invalid_states(self):
        """Test that operations are blocked when WebSocket is not connected"""
        from hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source import WebSocketState
            
        # Set disconnected state with no assistant
        self.data_source._ws_state = WebSocketState.DISCONNECTED
        self.data_source._ws_assistant = None
        
        # Try to send message - should be blocked (no assistant)
        result = self.data_source._can_send_message()
        self.assertFalse(result)
        
        # Set connected state but still no assistant
        self.data_source._ws_state = WebSocketState.CONNECTED
        self.data_source._ws_assistant = None
        
        # Should still be blocked (no assistant even though connected state)
        result = self.data_source._can_send_message()
        self.assertFalse(result)
        
        # Now set both state and assistant
        self.data_source._ws_state = WebSocketState.CONNECTED
        self.data_source._ws_assistant = MagicMock()  # Mock assistant
        
        # Now should be allowed (both conditions met)
        result = self.data_source._can_send_message()
        self.assertTrue(result)
        
        # Test disconnected state with assistant present
        self.data_source._ws_state = WebSocketState.DISCONNECTED
        # assistant still present
        
        # Should be blocked (wrong state even with assistant)
        result = self.data_source._can_send_message()
        self.assertFalse(result)
        
    def test_websocket_state_consistency(self):
        """Test that WebSocket state remains consistent through operations"""
        from hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source import WebSocketState
            
        # Start disconnected
        self.data_source._ws_state = WebSocketState.DISCONNECTED
        self.data_source._ws_assistant = None
        
        # Simulate connection process
        self.data_source._ws_state = WebSocketState.CONNECTING
        # During actual connection, assistant would be created
        mock_assistant = MagicMock()
        self.data_source._ws_assistant = mock_assistant
        self.data_source._ws_state = WebSocketState.CONNECTED
        
        # Verify state and assistant are consistent
        self.assertEqual(self.data_source._ws_state, WebSocketState.CONNECTED)
        self.assertIsNotNone(self.data_source._ws_assistant)
        self.assertTrue(self.data_source._can_send_message())
        
        # Simulate disconnection process
        self.data_source._ws_state = WebSocketState.DISCONNECTING
        # During actual disconnection, assistant would be cleaned up
        self.data_source._ws_assistant = None
        self.data_source._ws_state = WebSocketState.DISCONNECTED
        
        # Verify state and assistant are consistent after disconnect
        self.assertEqual(self.data_source._ws_state, WebSocketState.DISCONNECTED)
        self.assertIsNone(self.data_source._ws_assistant)
        self.assertFalse(self.data_source._can_send_message())
        
    # Integration Tests
    
    async def test_websocket_integration_error_recovery(self):
        """Integration test: verify complete error recovery flow"""
        # Simulate various error conditions
        ws_assistant = AsyncMock()
        
        error_messages = [
            MagicMock(data="malformed"),
            MagicMock(data={"invalid": "message"}),
            MagicMock(data={
                "stream": f"depth.{self.exchange_symbol}",
                "data": {
                    "asks": "invalid",
                    "bids": [],
                    "E": "not_a_number"
                }
            })
        ]
        
        valid_message = MagicMock(data={
            "stream": f"depth.{self.exchange_symbol}",
            "data": {
                "asks": [["10.5", "100"]],
                "bids": [["10.4", "150"]],
                "E": int(time.time() * 1e6)
            }
        })
        
        # Mix error and valid messages
        all_messages = error_messages + [valid_message]
        
        async def mock_iter():
            for msg in all_messages:
                yield msg
                
        ws_assistant.iter_messages = lambda: mock_iter()
        
        # Set up message queues
        self.data_source._message_queue = {
            self.data_source._diff_messages_queue_key: asyncio.Queue(),
            self.data_source._trade_messages_queue_key: asyncio.Queue()
        }
        
        # Process all messages
        with patch.object(self.data_source, "_parse_order_book_diff_message") as mock_parse:
            await self.data_source._process_websocket_messages(ws_assistant)
            
            # Only valid message should be parsed
            self.assertEqual(mock_parse.call_count, 1)
            
            # Warnings should be logged
            self.assertTrue(
                self._is_logged("WARNING", "non-dict") or 
                self._is_logged("WARNING", "missing")
            )
            
    # Helper Methods
    
    async def _async_iterator(self, items):
        """Helper to create async iterator from list"""
        for item in items:
            yield item
            
            
class NetworkMocking:
    """Helper class for network mocking"""
    
    def __init__(self):
        self.mock_responses = {}
        
    def add_response(self, url: str, response: Dict, status: int = 200):
        """Add a mock response for a URL"""
        self.mock_responses[url] = {"response": response, "status": status}
        
    def get_response(self, url: str):
        """Get mock response for a URL"""
        return self.mock_responses.get(url, {"response": {}, "status": 404})


if __name__ == "__main__":
    unittest.main()