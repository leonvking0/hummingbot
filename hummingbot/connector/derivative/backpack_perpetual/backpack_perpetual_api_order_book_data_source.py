import asyncio
import time
from typing import Any, Dict, List, Optional

import aiohttp

from hummingbot.connector.derivative.backpack_perpetual import (
    backpack_perpetual_constants as CONSTANTS,
    backpack_perpetual_utils as utils,
    backpack_perpetual_web_utils as web_utils
)
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.data_type.funding_info import FundingInfo, FundingInfoUpdate
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.perpetual_api_order_book_data_source import PerpetualAPIOrderBookDataSource
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.logger import HummingbotLogger


class BackpackPerpetualAPIOrderBookDataSource(PerpetualAPIOrderBookDataSource):
    """
    Data source for Backpack Perpetual Exchange order book tracking
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
                market_type = ticker.get("marketType", "")
                
                # Only process perpetual markets
                if market_type in CONSTANTS.PERPETUAL_MARKET_TYPES:
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
                # Only include perpetual markets
                if (market.get("status") == "ONLINE" and 
                    market.get("marketType") in CONSTANTS.PERPETUAL_MARKET_TYPES):
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

    async def get_funding_info(self, trading_pair: str) -> FundingInfo:
        """
        Get funding info for a trading pair

        :param trading_pair: The trading pair
        :return: FundingInfo instance
        """
        rest_assistant = await self._api_factory.get_rest_assistant()
        url = web_utils.get_funding_rate_url()
        
        exchange_symbol = utils.convert_to_exchange_trading_pair(trading_pair)
        params = {"symbol": exchange_symbol}
        
        try:
            response = await rest_assistant.execute_request(
                url=url,
                throttler_limit_id=CONSTANTS.FUNDING_RATE_PATH_URL,
                method=RESTMethod.GET,
                params=params,
            )
            
            funding_data = utils.parse_funding_info(response)
            
            return FundingInfo(
                trading_pair=trading_pair,
                index_price=response.get("indexPrice", 0),
                mark_price=response.get("markPrice", 0),
                next_funding_utc_timestamp=funding_data["next_funding_timestamp"],
                rate=funding_data["funding_rate"],
            )
            
        except Exception as e:
            self.logger().error(
                f"Error fetching funding info for {trading_pair}. Error: {str(e)}",
                exc_info=True
            )
            # Return default funding info
            return FundingInfo(
                trading_pair=trading_pair,
                index_price=0,
                mark_price=0,
                next_funding_utc_timestamp=time.time() + CONSTANTS.FUNDING_RATE_INTERVAL_HOURS * 3600,
                rate=0,
            )

    async def listen_for_subscriptions(self):
        """
        Listen for subscription acknowledgments
        Not implemented for Backpack as it doesn't send explicit subscription confirmations
        """
        pass

    async def listen_for_trades(self, ev_loop: asyncio.AbstractEventLoop, output: asyncio.Queue):
        """
        Listen for trade events via WebSocket

        :param ev_loop: Event loop
        :param output: Output queue for trade messages
        """
        while True:
            try:
                ws_assistant = await self._api_factory.get_ws_assistant()
                await ws_assistant.connect(
                    ws_url=web_utils.wss_url(self._domain),
                    ping_timeout=CONSTANTS.WS_HEARTBEAT_TIMEOUT
                )
                
                # Subscribe to trade streams for all trading pairs
                subscribe_tasks = []
                for trading_pair in self._trading_pairs:
                    exchange_symbol = utils.convert_to_exchange_trading_pair(trading_pair)
                    stream_name = web_utils.get_ws_stream_name(CONSTANTS.WS_TRADES_STREAM, exchange_symbol)
                    subscribe_msg = web_utils.create_ws_subscribe_message([stream_name])
                    subscribe_request = WSJSONRequest(payload=subscribe_msg)
                    subscribe_tasks.append(ws_assistant.send(subscribe_request))
                
                await asyncio.gather(*subscribe_tasks)
                
                async for ws_response in ws_assistant.iter_messages():
                    data = ws_response.data
                    if isinstance(data, dict) and "stream" in data:
                        stream_data = data.get("data", {})
                        stream_name = data.get("stream", "")
                        
                        if stream_name.startswith(f"{CONSTANTS.WS_TRADES_STREAM}."):
                            # Extract trading pair from stream name
                            exchange_symbol = stream_name.split(".")[-1]
                            trading_pair = utils.convert_from_exchange_trading_pair(exchange_symbol)
                            
                            trade_msg = self._parse_trade_message(stream_data, trading_pair)
                            output.put_nowait(trade_msg)
                            
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger().error(
                    f"Unexpected error in trades listener. Error: {str(e)}",
                    exc_info=True
                )
                await self._sleep(5.0)
            finally:
                if ws_assistant:
                    await ws_assistant.disconnect()

    async def listen_for_order_book_diffs(self, ev_loop: asyncio.AbstractEventLoop, output: asyncio.Queue):
        """
        Listen for order book diff events via WebSocket

        :param ev_loop: Event loop
        :param output: Output queue for order book messages
        """
        while True:
            try:
                ws_assistant = await self._api_factory.get_ws_assistant()
                await ws_assistant.connect(
                    ws_url=web_utils.wss_url(self._domain),
                    ping_timeout=CONSTANTS.WS_HEARTBEAT_TIMEOUT
                )
                
                # Subscribe to depth streams for all trading pairs
                subscribe_tasks = []
                for trading_pair in self._trading_pairs:
                    exchange_symbol = utils.convert_to_exchange_trading_pair(trading_pair)
                    stream_name = web_utils.get_ws_stream_name(CONSTANTS.WS_DEPTH_STREAM, exchange_symbol)
                    subscribe_msg = web_utils.create_ws_subscribe_message([stream_name])
                    subscribe_request = WSJSONRequest(payload=subscribe_msg)
                    subscribe_tasks.append(ws_assistant.send(subscribe_request))
                
                await asyncio.gather(*subscribe_tasks)
                
                async for ws_response in ws_assistant.iter_messages():
                    data = ws_response.data
                    if isinstance(data, dict) and "stream" in data:
                        stream_data = data.get("data", {})
                        stream_name = data.get("stream", "")
                        
                        if stream_name.startswith(f"{CONSTANTS.WS_DEPTH_STREAM}."):
                            # Extract trading pair from stream name
                            exchange_symbol = stream_name.split(".")[-1]
                            trading_pair = utils.convert_from_exchange_trading_pair(exchange_symbol)
                            
                            # Parse the depth update
                            timestamp = stream_data.get("E", time.time() * 1000) / 1000  # Convert from microseconds
                            order_book_msg = utils.parse_order_book_diff(
                                diff_data=stream_data,
                                trading_pair=trading_pair,
                                timestamp=timestamp
                            )
                            output.put_nowait(order_book_msg)
                            
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger().error(
                    f"Unexpected error in order book diff listener. Error: {str(e)}",
                    exc_info=True
                )
                await self._sleep(5.0)
            finally:
                if ws_assistant:
                    await ws_assistant.disconnect()

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

    async def listen_for_funding_info(self, output: asyncio.Queue):
        """
        Listen for funding info updates

        :param output: Output queue for funding info updates
        """
        while True:
            try:
                ws_assistant = await self._api_factory.get_ws_assistant()
                await ws_assistant.connect(
                    ws_url=web_utils.wss_url(self._domain),
                    ping_timeout=CONSTANTS.WS_HEARTBEAT_TIMEOUT
                )
                
                # Subscribe to funding rate streams for all trading pairs
                subscribe_tasks = []
                for trading_pair in self._trading_pairs:
                    exchange_symbol = utils.convert_to_exchange_trading_pair(trading_pair)
                    stream_name = web_utils.get_ws_stream_name(CONSTANTS.WS_FUNDING_RATE_STREAM, exchange_symbol)
                    subscribe_msg = web_utils.create_ws_subscribe_message([stream_name])
                    subscribe_request = WSJSONRequest(payload=subscribe_msg)
                    subscribe_tasks.append(ws_assistant.send(subscribe_request))
                
                await asyncio.gather(*subscribe_tasks)
                
                async for ws_response in ws_assistant.iter_messages():
                    data = ws_response.data
                    if isinstance(data, dict) and "stream" in data:
                        stream_data = data.get("data", {})
                        stream_name = data.get("stream", "")
                        
                        if stream_name.startswith(f"{CONSTANTS.WS_FUNDING_RATE_STREAM}."):
                            # Extract trading pair from stream name
                            exchange_symbol = stream_name.split(".")[-1]
                            trading_pair = utils.convert_from_exchange_trading_pair(exchange_symbol)
                            
                            # Parse funding update
                            funding_data = utils.parse_funding_info(stream_data)
                            
                            funding_update = FundingInfoUpdate(
                                trading_pair=trading_pair,
                                index_price=stream_data.get("indexPrice", 0),
                                mark_price=stream_data.get("markPrice", 0),
                                next_funding_utc_timestamp=funding_data["next_funding_timestamp"],
                                rate=funding_data["funding_rate"],
                            )
                            
                            output.put_nowait(funding_update)
                            
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger().error(
                    f"Unexpected error in funding info listener. Error: {str(e)}",
                    exc_info=True
                )
                await self._sleep(5.0)
            finally:
                if ws_assistant:
                    await ws_assistant.disconnect()

    def _parse_trade_message(self, trade_data: Dict[str, Any], trading_pair: str) -> OrderBookMessage:
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

    async def _parse_funding_info_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        """
        Parse funding info message from raw WebSocket message
        
        :param raw_message: Raw message from WebSocket
        :param message_queue: Queue to put parsed funding info updates
        """
        # For Backpack, we handle this in listen_for_funding_info directly
        # This method is required by the abstract base class but not used in our implementation
        pass