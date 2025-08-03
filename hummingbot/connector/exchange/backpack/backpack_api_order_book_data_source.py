import asyncio
import time
from enum import Enum
from typing import Any, Dict, List, Optional

import aiohttp

from hummingbot.connector.exchange.backpack import (
    backpack_constants as CONSTANTS,
    backpack_utils as utils,
    backpack_web_utils as web_utils
)
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant
from hummingbot.logger import HummingbotLogger


class WebSocketState(Enum):
    """WebSocket connection state management"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    RECONNECTING = "reconnecting"
    
    @property
    def is_connected(self):
        """Check if state represents an active connection"""
        return self == WebSocketState.CONNECTED
        
    @property
    def can_send(self):
        """Check if state allows sending messages"""
        return self == WebSocketState.CONNECTED


class BackpackAPIOrderBookDataSource(OrderBookTrackerDataSource):
    """
    Data source for Backpack Exchange order book tracking
    """

    _logger: Optional[HummingbotLogger] = None

    def __init__(
        self,
        trading_pairs: List[str],
        throttler: Optional[AsyncThrottler] = None,
        api_factory: Optional[WebAssistantsFactory] = None,
        domain: str = CONSTANTS.DEFAULT_DOMAIN,
    ):
        super().__init__(trading_pairs)
        self._throttler = throttler or self._get_throttler_instance()
        self._api_factory = api_factory or web_utils.build_api_factory(throttler=self._throttler)
        self._domain = domain
        self._trading_pairs = trading_pairs
        self._snapshot_msg: Dict[str, OrderBookMessage] = {}
        self._ws_assistant = None
        
        # WebSocket reliability improvements
        self.MAX_RECONNECT_ATTEMPTS = 10
        self.MAX_DROPPED_MESSAGES = 100
        self._dropped_messages_count = 0
        self._last_heartbeat = time.time()
        self._ws_state = WebSocketState.DISCONNECTED
        self._reconnect_task = None
        self._heartbeat_task = None
        self._monitor_task = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = HummingbotLogger(__name__)
        return cls._logger

    async def get_last_traded_prices(self, trading_pairs: List[str]) -> Dict[str, float]:
        """
        Get the last traded prices for the given trading pairs

        :param trading_pairs: List of trading pairs
        :return: Dictionary mapping trading pair to last traded price
        """
        results = {}
        
        # Fetch all tickers at once
        rest_assistant = await self._api_factory.get_rest_assistant()
        url = web_utils.get_ticker_url()
        
        try:
            response = await rest_assistant.execute_request(
                url=url,
                throttler_limit_id=CONSTANTS.TICKER_PATH_URL,
                method=RESTMethod.GET,
            )
            
            # Parse response - it's a list of all tickers
            for ticker in response:
                symbol = ticker.get("symbol", "")
                hb_trading_pair = utils.convert_from_exchange_trading_pair(symbol)
                
                if hb_trading_pair in trading_pairs:
                    last_price = float(ticker.get("lastPrice", 0))
                    results[hb_trading_pair] = last_price
                    
        except Exception as e:
            self.logger().error(
                f"Error fetching last traded prices. Error: {str(e)}",
                exc_info=True
            )
        
        return results

    async def fetch_trading_pairs(self) -> List[str]:
        """
        Fetch all available trading pairs from the exchange

        :return: List of trading pairs in Hummingbot format
        """
        rest_assistant = await self._api_factory.get_rest_assistant()
        url = web_utils.get_markets_url()
        
        try:
            response = await rest_assistant.execute_request(
                url=url,
                throttler_limit_id=CONSTANTS.MARKETS_PATH_URL,
                method=RESTMethod.GET,
            )
            
            trading_pairs = []
            for market in response:
                if market.get("status") == "ONLINE":
                    symbol = market.get("symbol", "")
                    if symbol:
                        hb_trading_pair = utils.convert_from_exchange_trading_pair(symbol)
                        trading_pairs.append(hb_trading_pair)
            
            return trading_pairs
            
        except Exception as e:
            self.logger().error(
                f"Error fetching trading pairs. Error: {str(e)}",
                exc_info=True
            )
            return []

    async def get_order_book_data(self, trading_pair: str) -> Dict[str, Any]:
        """
        Get order book snapshot data for a trading pair

        :param trading_pair: The trading pair
        :return: Order book data
        """
        rest_assistant = await self._api_factory.get_rest_assistant()
        url = web_utils.get_order_book_url(trading_pair)
        
        exchange_symbol = utils.convert_to_exchange_trading_pair(trading_pair)
        params = {"symbol": exchange_symbol}
        
        response = await rest_assistant.execute_request(
            url=url,
            throttler_limit_id=CONSTANTS.DEPTH_PATH_URL,
            method=RESTMethod.GET,
            params=params,
        )
        
        return response

    async def get_new_order_book(self, trading_pair: str) -> OrderBook:
        """
        Create a new order book for the trading pair

        :param trading_pair: The trading pair
        :return: OrderBook instance
        """
        snapshot = await self.get_order_book_data(trading_pair)
        snapshot_timestamp = time.time()
        snapshot_msg = utils.parse_order_book_snapshot(
            snapshot_data=snapshot,
            trading_pair=trading_pair,
            timestamp=snapshot_timestamp
        )
        order_book = OrderBook()
        order_book.apply_snapshot(
            snapshot_msg.bids,
            snapshot_msg.asks,
            snapshot_msg.update_id
        )
        return order_book

    async def _connected_websocket_assistant(self) -> WSAssistant:
        """
        Creates an instance of WSAssistant connected to the exchange with state management.
        """
        # Update state to connecting
        self._set_ws_state(WebSocketState.CONNECTING)
        
        try:
            ws_assistant = await self._api_factory.get_ws_assistant()
            await ws_assistant.connect(
                ws_url=web_utils.wss_url(self._domain),
                ping_timeout=CONSTANTS.WS_HEARTBEAT_TIMEOUT
            )
            
            # Update state to connected on successful connection
            self._set_ws_state(WebSocketState.CONNECTED)
            self._ws_assistant = ws_assistant
            
            # Start heartbeat and monitoring tasks
            self._heartbeat_task = asyncio.create_task(self._send_heartbeat(ws_assistant))
            self._monitor_task = asyncio.create_task(self._monitor_heartbeat())
            
            return ws_assistant
        except Exception as e:
            # Update state back to disconnected on failure
            self._set_ws_state(WebSocketState.DISCONNECTED)
            raise e

    async def _subscribe_channels(self, ws: WSAssistant):
        """
        Subscribe to order book and trade channels for all trading pairs.
        """
        # Subscribe to depth and trade streams for all trading pairs
        subscribe_tasks = []
        for trading_pair in self._trading_pairs:
            exchange_symbol = utils.convert_to_exchange_trading_pair(trading_pair)
            
            # Subscribe to depth stream
            depth_stream_name = web_utils.get_ws_stream_name(CONSTANTS.WS_DEPTH_STREAM, exchange_symbol)
            depth_subscribe_msg = web_utils.create_ws_subscribe_message([depth_stream_name])
            depth_subscribe_request = WSJSONRequest(payload=depth_subscribe_msg)
            subscribe_tasks.append(ws.send(depth_subscribe_request))
            
            # Subscribe to trades stream
            trades_stream_name = web_utils.get_ws_stream_name(CONSTANTS.WS_TRADES_STREAM, exchange_symbol)
            trades_subscribe_msg = web_utils.create_ws_subscribe_message([trades_stream_name])
            trades_subscribe_request = WSJSONRequest(payload=trades_subscribe_msg)
            subscribe_tasks.append(ws.send(trades_subscribe_request))
        
        await asyncio.gather(*subscribe_tasks)
        self.logger().info(f"Subscribed to order book and trade channels for {self._trading_pairs}")

    def _channel_originating_message(self, event_message: Dict[str, Any]) -> str:
        """
        Identifies the channel for a particular event message
        :param event_message: the event received through the websocket connection
        :return: the message channel
        """
        channel = ""
        if isinstance(event_message, dict) and "stream" in event_message:
            stream_name = event_message.get("stream", "")
            # Parse stream name format: <type>.<symbol>
            if stream_name.startswith(f"{CONSTANTS.WS_DEPTH_STREAM}."):
                channel = self._diff_messages_queue_key
            elif stream_name.startswith(f"{CONSTANTS.WS_TRADES_STREAM}."):
                channel = self._trade_messages_queue_key
        return channel

    async def _parse_order_book_diff_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        """
        Parse order book diff message and add to queue with error handling
        """
        try:
            if "data" not in raw_message or "stream" not in raw_message:
                self.logger().warning("Order book message missing required fields")
                return
                
            stream_name = raw_message["stream"]
            data = raw_message["data"]
            
            # Validate data structure
            if not isinstance(data, dict):
                self.logger().warning(f"Invalid order book data type: {type(data).__name__}")
                return
                
            # Extract trading pair from stream name (format: depth.SOL_USDC)
            exchange_symbol = stream_name.split(".")[-1]
            trading_pair = utils.convert_from_exchange_trading_pair(exchange_symbol)
            
            # Get timestamp from data or use current time (fixed: use microseconds consistently)
            timestamp = data.get("E", time.time() * 1e6) / 1e6  # Convert microseconds to seconds
            
            order_book_msg = utils.parse_order_book_diff(
                diff_data=data,
                trading_pair=trading_pair,
                timestamp=timestamp
            )
            
            # Handle queue overflow
            try:
                message_queue.put_nowait(order_book_msg)
            except asyncio.QueueFull:
                self.logger().warning(f"Order book message queue full for {trading_pair}, dropping message")
                self._handle_queue_overflow(trading_pair)
                
        except Exception as e:
            self.logger().error(
                f"Error parsing order book diff message: {e}\n"
                f"Raw message: {raw_message}",
                exc_info=True
            )

    async def _parse_trade_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        """
        Parse trade message and add to queue with error handling
        """
        try:
            if "data" not in raw_message or "stream" not in raw_message:
                self.logger().warning("Trade message missing required fields")
                return
                
            stream_name = raw_message["stream"]
            data = raw_message["data"]
            
            # Validate data structure
            if not isinstance(data, dict):
                self.logger().warning(f"Invalid trade data type: {type(data).__name__}")
                return
                
            # Extract trading pair from stream name (format: trades.SOL_USDC)
            exchange_symbol = stream_name.split(".")[-1]
            trading_pair = utils.convert_from_exchange_trading_pair(exchange_symbol)
            
            trade_msg = self._parse_trade_message_data(data, trading_pair)
            
            # Handle queue overflow
            try:
                message_queue.put_nowait(trade_msg)
            except asyncio.QueueFull:
                self.logger().warning(f"Trade message queue full for {trading_pair}, dropping message")
                self._handle_queue_overflow(trading_pair)
                
        except Exception as e:
            self.logger().error(
                f"Error parsing trade message: {e}\n"
                f"Raw message: {raw_message}",
                exc_info=True
            )

    async def _process_websocket_messages(self, websocket_assistant: WSAssistant):
        """
        Process messages from websocket with robust error handling
        """
        async for ws_response in websocket_assistant.iter_messages():
            try:
                data = ws_response.data
                
                # Handle non-dict data (e.g., malformed JSON)
                if not isinstance(data, dict):
                    self.logger().warning(f"Received non-dict WebSocket message: {type(data).__name__}")
                    continue
                    
                # Check for required 'stream' field
                if not data.get("stream"):
                    self.logger().warning("WebSocket message missing 'stream' field")
                    continue
                    
                channel = self._channel_originating_message(data)
                if channel == self._diff_messages_queue_key:
                    await self._parse_order_book_diff_message(data, self._message_queue[channel])
                elif channel == self._trade_messages_queue_key:
                    await self._parse_trade_message(data, self._message_queue[channel])
                    
            except Exception as e:
                self.logger().error(
                    f"Error processing WebSocket message: {e}\n"
                    f"Message data: {ws_response.data if hasattr(ws_response, 'data') else 'N/A'}",
                    exc_info=True
                )
                # Continue processing other messages instead of breaking the loop

    async def _on_order_stream_interruption(self, websocket_assistant: Optional[WSAssistant]):
        """Clean up on websocket interruption and attempt reconnection with exponential backoff"""
        # Update state to disconnecting if not already disconnected
        if self._ws_state != WebSocketState.DISCONNECTED:
            self._set_ws_state(WebSocketState.DISCONNECTING)
            
        if websocket_assistant:
            await websocket_assistant.disconnect()
        self._ws_assistant = None
        
        # Update state to disconnected
        self._set_ws_state(WebSocketState.DISCONNECTED)
        
        # Cancel existing tasks
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._monitor_task:
            self._monitor_task.cancel()
            self._monitor_task = None
            
        # Update state to reconnecting
        self._set_ws_state(WebSocketState.RECONNECTING)
        
        # Attempt reconnection with exponential backoff
        for attempt in range(self.MAX_RECONNECT_ATTEMPTS):
            delay = min(2 ** attempt, 30)  # Start at 1s, double each time, max 30s
            self.logger().info(f"WebSocket reconnection attempt {attempt + 1}/{self.MAX_RECONNECT_ATTEMPTS} in {delay}s")
            await asyncio.sleep(delay)
            
            try:
                # Try to reconnect (this will handle state updates)
                self._ws_assistant = await self._connected_websocket_assistant()
                await self._subscribe_channels(self._ws_assistant)
                self.logger().info("Successfully reconnected to WebSocket")
                
                # Reset dropped message counter on successful reconnection
                self._dropped_messages_count = 0
                
                # Restart heartbeat and monitoring tasks
                if self._ws_assistant:
                    self._heartbeat_task = asyncio.create_task(self._send_heartbeat(self._ws_assistant))
                    self._monitor_task = asyncio.create_task(self._monitor_heartbeat())
                
                break
            except Exception as e:
                self.logger().error(f"Reconnection attempt {attempt + 1} failed: {e}")
                if attempt == self.MAX_RECONNECT_ATTEMPTS - 1:
                    self.logger().critical("Max reconnection attempts reached. WebSocket connection failed.")
                    self._set_ws_state(WebSocketState.DISCONNECTED)

    def _handle_queue_overflow(self, trading_pair: str):
        """Handle message queue overflow by tracking dropped messages"""
        self._dropped_messages_count += 1
        
        if self._dropped_messages_count > self.MAX_DROPPED_MESSAGES:
            self.logger().error(
                f"Too many dropped messages ({self._dropped_messages_count}), "
                "triggering WebSocket reconnection"
            )
            # Schedule reconnection
            if self._ws_assistant and not self._reconnect_task:
                self._reconnect_task = asyncio.create_task(
                    self._on_order_stream_interruption(self._ws_assistant)
                )
                
    async def _send_heartbeat(self, websocket_assistant: WSAssistant):
        """Send periodic heartbeat to keep WebSocket connection alive"""
        while self._ws_assistant:
            try:
                await asyncio.sleep(CONSTANTS.WS_HEARTBEAT_INTERVAL)
                if self._ws_assistant:
                    # Send ping message
                    ping_message = {"op": "ping"}
                    await websocket_assistant.send(WSJSONRequest(payload=ping_message))
                    self._last_heartbeat = time.time()
                    self.logger().debug("Sent WebSocket heartbeat ping")
            except Exception as e:
                self.logger().error(f"Error sending heartbeat: {e}")
                await self._on_order_stream_interruption(websocket_assistant)
                break
                
    async def _monitor_heartbeat(self):
        """Monitor heartbeat responses and trigger reconnection on timeout"""
        while self._ws_assistant:
            await asyncio.sleep(CONSTANTS.WS_HEARTBEAT_TIMEOUT)
            
            time_since_heartbeat = time.time() - self._last_heartbeat
            if time_since_heartbeat > CONSTANTS.WS_HEARTBEAT_TIMEOUT:
                self.logger().warning(
                    f"Heartbeat timeout ({time_since_heartbeat:.1f}s since last heartbeat), "
                    "reconnecting WebSocket"
                )
                await self._on_order_stream_interruption(self._ws_assistant)
                break
                
    async def _check_dropped_messages(self):
        """Check if too many messages have been dropped and trigger reconnection if needed"""
        if self._dropped_messages_count > self.MAX_DROPPED_MESSAGES:
            self.logger().error("Too many dropped messages, reconnecting...")
            await self._on_order_stream_interruption(self._ws_assistant)
            
    def _can_send_message(self) -> bool:
        """Check if WebSocket is in a state that allows sending messages"""
        return (
            self._ws_assistant is not None and 
            self._ws_state == WebSocketState.CONNECTED
        )
        
    def _set_ws_state(self, new_state: WebSocketState):
        """Set WebSocket state with validation"""
        old_state = self._ws_state
        
        # Validate state transition
        valid_transitions = {
            WebSocketState.DISCONNECTED: [WebSocketState.CONNECTING, WebSocketState.RECONNECTING],
            WebSocketState.CONNECTING: [WebSocketState.CONNECTED, WebSocketState.DISCONNECTED],
            WebSocketState.CONNECTED: [WebSocketState.DISCONNECTING, WebSocketState.RECONNECTING],
            WebSocketState.DISCONNECTING: [WebSocketState.DISCONNECTED],
            WebSocketState.RECONNECTING: [WebSocketState.CONNECTED, WebSocketState.DISCONNECTED]
        }
        
        if old_state and new_state not in valid_transitions.get(old_state, []):
            self.logger().warning(
                f"Invalid state transition from {old_state.value} to {new_state.value}"
            )
            
        self._ws_state = new_state
        self.logger().debug(f"WebSocket state changed from {old_state.value if old_state else 'None'} to {new_state.value}")

    async def listen_for_trades(self, ev_loop: asyncio.AbstractEventLoop, output: asyncio.Queue):
        """
        Listen for trade events via WebSocket
        This is now handled by the unified listen_for_subscriptions method
        """
        # Trade messages are handled by the base class listen_for_subscriptions
        message_queue = self._message_queue[self._trade_messages_queue_key]
        while True:
            try:
                order_book_message = await message_queue.get()
                output.put_nowait(order_book_message)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception("Unexpected error when listening for trades.")
                await self._sleep(5.0)

    async def listen_for_order_book_diffs(self, ev_loop: asyncio.AbstractEventLoop, output: asyncio.Queue):
        """
        Listen for order book diff events via WebSocket
        This is now handled by the unified listen_for_subscriptions method
        """
        # Order book diff messages are handled by the base class listen_for_subscriptions
        message_queue = self._message_queue[self._diff_messages_queue_key]
        while True:
            try:
                order_book_message = await message_queue.get()
                output.put_nowait(order_book_message)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception("Unexpected error when listening for order book diffs.")
                await self._sleep(5.0)

    async def listen_for_order_book_snapshots(self, ev_loop: asyncio.AbstractEventLoop, output: asyncio.Queue):
        """
        Periodically fetch order book snapshots

        :param ev_loop: Event loop
        :param output: Output queue for order book messages
        """
        # Backpack provides incremental updates via WebSocket
        # We only need initial snapshots, which are fetched in get_new_order_book
        # This method can remain empty or fetch periodic snapshots if needed
        while True:
            try:
                await self._sleep(300)  # Sleep for 5 minutes
                # Optionally fetch snapshots periodically for verification
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger().error(
                    f"Unexpected error in snapshot listener. Error: {str(e)}",
                    exc_info=True
                )

    def _parse_trade_message_data(self, trade_data: Dict[str, Any], trading_pair: str) -> OrderBookMessage:
        """
        Parse trade message from WebSocket

        :param trade_data: Raw trade data
        :param trading_pair: Trading pair
        :return: OrderBookMessage for trade
        """
        # Fixed: Backpack uses microseconds, convert to seconds consistently
        timestamp = trade_data.get("E", time.time() * 1e6) / 1e6  # Convert from microseconds
        
        trade_info = {
            "trading_pair": trading_pair,
            "trade_type": float(trade_data.get("m", True)),  # Is buyer maker
            "trade_id": trade_data.get("t", 0),
            "price": trade_data.get("p", "0"),
            "amount": trade_data.get("q", "0"),
            "trade_timestamp": trade_data.get("T", timestamp * 1000) / 1000,
        }
        
        return OrderBookMessage(
            message_type=OrderBookMessageType.TRADE,
            content=trade_info,
            timestamp=timestamp
        )

    def _get_throttler_instance(self) -> AsyncThrottler:
        """Get throttler instance with configured rate limits"""
        throttler = AsyncThrottler(CONSTANTS.RATE_LIMITS)
        return throttler