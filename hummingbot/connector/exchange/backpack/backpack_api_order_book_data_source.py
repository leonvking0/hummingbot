import asyncio
import time
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
        
        # Reconnection strategy parameters
        self._reconnect_delay = 1.0  # Start with 1 second delay
        self._max_reconnect_delay = 60.0  # Maximum 60 seconds delay
        self._reconnect_factor = 2.0  # Exponential backoff factor
        self._consecutive_failures = 0  # Track consecutive connection failures
        
        # Connection health monitoring
        self._last_message_time = 0.0  # Timestamp of last received message
        self._connection_timeout = 120.0  # 2 minutes without messages = stale connection
        self._health_check_task: Optional[asyncio.Task] = None
        self._health_check_interval = 30.0  # Check connection health every 30 seconds

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
        Creates an instance of WSAssistant connected to the exchange.
        """
        ws_assistant = await self._api_factory.get_ws_assistant()
        await ws_assistant.connect(
            ws_url=web_utils.wss_url(self._domain),
            ping_timeout=CONSTANTS.WS_HEARTBEAT_TIMEOUT
        )
        return ws_assistant

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
        Parse order book diff message and add to queue
        """
        if "data" in raw_message and "stream" in raw_message:
            stream_name = raw_message["stream"]
            data = raw_message["data"]
            
            # Extract trading pair from stream name (format: depth.SOL_USDC)
            exchange_symbol = stream_name.split(".")[-1]
            trading_pair = utils.convert_from_exchange_trading_pair(exchange_symbol)
            
            # Get timestamp from data or use current time
            timestamp = data.get("E", time.time() * 1000) / 1e6  # Convert microseconds to seconds
            
            order_book_msg = utils.parse_order_book_diff(
                diff_data=data,
                trading_pair=trading_pair,
                timestamp=timestamp
            )
            message_queue.put_nowait(order_book_msg)

    async def _parse_trade_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        """
        Parse trade message and add to queue
        """
        if "data" in raw_message and "stream" in raw_message:
            stream_name = raw_message["stream"]
            data = raw_message["data"]
            
            # Extract trading pair from stream name (format: trades.SOL_USDC)
            exchange_symbol = stream_name.split(".")[-1]
            trading_pair = utils.convert_from_exchange_trading_pair(exchange_symbol)
            
            trade_msg = self._parse_trade_message_data(data, trading_pair)
            message_queue.put_nowait(trade_msg)

    async def _process_websocket_messages(self, websocket_assistant: WSAssistant):
        """
        Process messages from websocket
        """
        async for ws_response in websocket_assistant.iter_messages():
            # Update last message time for health monitoring
            self._last_message_time = time.time()
            
            data = ws_response.data
            if isinstance(data, dict) and data.get("stream"):
                channel = self._channel_originating_message(data)
                if channel == self._diff_messages_queue_key:
                    await self._parse_order_book_diff_message(data, self._message_queue[channel])
                elif channel == self._trade_messages_queue_key:
                    await self._parse_trade_message(data, self._message_queue[channel])

    async def _monitor_connection_health(self, ws: WSAssistant):
        """
        Monitor the health of the WebSocket connection.
        Raises ConnectionError if no messages received within timeout period.
        """
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                
                # Check if connection is stale
                time_since_last_message = time.time() - self._last_message_time
                if time_since_last_message > self._connection_timeout:
                    raise ConnectionError(
                        f"Connection appears stale. No messages received for {time_since_last_message:.1f} seconds"
                    )
                
                # Log connection health status
                self.logger().debug(
                    f"Connection health check passed. Last message received {time_since_last_message:.1f} seconds ago"
                )
                
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger().warning(f"Connection health check failed: {str(e)}")
                raise

    async def _on_order_stream_interruption(self, websocket_assistant: Optional[WSAssistant]):
        """Clean up on websocket interruption"""
        # Cancel health check task if running
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        if websocket_assistant:
            await websocket_assistant.disconnect()
        self._ws_assistant = None

    async def listen_for_subscriptions(self):
        """
        Connects to the trade events and order diffs websocket endpoints and listens to the messages sent by the
        exchange. Each message is stored in its own queue.
        
        This implementation includes exponential backoff for reconnection attempts.
        """
        ws: Optional[WSAssistant] = None
        while True:
            try:
                # Calculate current reconnection delay
                current_delay = min(
                    self._reconnect_delay * (self._reconnect_factor ** self._consecutive_failures),
                    self._max_reconnect_delay
                )
                
                # If this is a reconnection attempt, wait before reconnecting
                if self._consecutive_failures > 0:
                    self.logger().warning(
                        f"WebSocket disconnected. Attempting reconnection #{self._consecutive_failures} "
                        f"in {current_delay:.1f} seconds..."
                    )
                    await self._sleep(current_delay)
                
                # Connect to WebSocket
                self.logger().info("Connecting to Backpack WebSocket...")
                ws = await self._connected_websocket_assistant()
                self._ws_assistant = ws
                
                # Subscribe to channels
                await self._subscribe_channels(ws)
                self.logger().info("Successfully connected and subscribed to WebSocket channels")
                
                # Reset failure count and initialize health monitoring on successful connection
                self._consecutive_failures = 0
                self._last_message_time = time.time()
                
                # Start health monitoring task
                self._health_check_task = asyncio.create_task(self._monitor_connection_health(ws))
                
                # Process messages
                await self._process_websocket_messages(websocket_assistant=ws)
                
            except asyncio.CancelledError:
                raise
            except ConnectionError as connection_exception:
                self._consecutive_failures += 1
                self.logger().warning(
                    f"WebSocket connection error ({connection_exception}). "
                    f"Total consecutive failures: {self._consecutive_failures}"
                )
            except Exception as e:
                self._consecutive_failures += 1
                self.logger().exception(
                    f"Unexpected error in WebSocket connection. "
                    f"Total consecutive failures: {self._consecutive_failures}. "
                    f"Error: {str(e)}"
                )
            finally:
                await self._on_order_stream_interruption(websocket_assistant=ws)
                ws = None

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
        timestamp = trade_data.get("E", time.time() * 1000) / 1000  # Convert from microseconds
        
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