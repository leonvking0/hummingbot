import asyncio
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant
from hummingbot.logger import HummingbotLogger

if TYPE_CHECKING:
    from .backpack_exchange import BackpackExchange


class BackpackAPIOrderBookDataSource(OrderBookTrackerDataSource):
    """Order book data source for Backpack exchange."""

    _logger: Optional[HummingbotLogger] = None

    def __init__(self,
                 trading_pairs: List[str],
                 connector: 'BackpackExchange',
                 api_factory: WebAssistantsFactory,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN):
        super().__init__(trading_pairs)
        self._connector = connector
        self._api_factory = api_factory
        self._domain = domain
        self._channel_associated_to_pair: Dict[str, str] = {}

    async def get_last_traded_prices(self,
                                     trading_pairs: List[str],
                                     domain: Optional[str] = None) -> Dict[str, float]:
        return await self._connector.get_last_traded_prices(trading_pairs=trading_pairs)

    async def _request_order_book_snapshot(self, trading_pair: str) -> Dict[str, Any]:
        params = {
            "symbol": await self._connector.exchange_symbol_associated_to_pair(trading_pair=trading_pair),
        }
        rest_assistant = await self._api_factory.get_rest_assistant()
        data = await rest_assistant.execute_request(
            url=f"{CONSTANTS.REST_URL}{CONSTANTS.ORDER_BOOK_PATH_URL}",
            params=params,
            method=RESTMethod.GET,
            throttler_limit_id=CONSTANTS.ORDER_BOOK_PATH_URL,
        )
        return data

    async def _order_book_snapshot(self, trading_pair: str) -> OrderBookMessage:
        snapshot = await self._request_order_book_snapshot(trading_pair)
        timestamp = float(snapshot.get("ts")) / 1000
        message = {
            "trading_pair": trading_pair,
            "update_id": timestamp,
            "bids": snapshot.get("bids", []),
            "asks": snapshot.get("asks", []),
        }
        return OrderBookMessage(OrderBookMessageType.SNAPSHOT, message, timestamp)

    async def _connected_websocket_assistant(self) -> WSAssistant:
        ws: WSAssistant = await self._api_factory.get_ws_assistant()
        await ws.connect(
            ws_url=CONSTANTS.WSS_PUBLIC_URL,
            ping_timeout=CONSTANTS.WS_HEARTBEAT_TIME_INTERVAL,
        )
        return ws

    async def _subscribe_channels(self, ws: WSAssistant):
        try:
            for trading_pair in self._trading_pairs:
                symbol = await self._connector.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
                trade_payload = {"op": "subscribe", "channel": f"trades.{symbol}"}
                depth_payload = {"op": "subscribe", "channel": f"depth.{symbol}"}
                await ws.send(WSJSONRequest(payload=trade_payload))
                await ws.send(WSJSONRequest(payload=depth_payload))
                self._channel_associated_to_pair[f"trades.{symbol}"] = trading_pair
                self._channel_associated_to_pair[f"depth.{symbol}"] = trading_pair
            self.logger().info("Subscribed to public order book and trade channels...")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger().error(
                "Unexpected error occurred subscribing to order book trading and delta streams...",
                exc_info=True,
            )
            raise

    async def _parse_trade_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        channel = raw_message.get("channel")
        trading_pair = self._channel_associated_to_pair.get(channel)
        data = raw_message.get("data") or {}
        trades = data if isinstance(data, list) else [data]
        for trade in trades:
            ts = float(trade.get("ts") or trade.get("t", time.time() * 1000)) / 1000
            side = str(trade.get("side", "buy")).lower()
            price = float(trade.get("p") or trade.get("price"))
            amount = float(trade.get("q") or trade.get("size"))
            message = OrderBookMessage(
                OrderBookMessageType.TRADE,
                {
                    "trading_pair": trading_pair,
                    "trade_type": 1.0 if side == "buy" else 2.0,
                    "trade_id": ts,
                    "update_id": ts,
                    "price": price,
                    "amount": amount,
                },
                ts,
            )
            message_queue.put_nowait(message)

    async def _parse_order_book_diff_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        channel = raw_message.get("channel")
        trading_pair = self._channel_associated_to_pair.get(channel)
        data = raw_message.get("data") or {}
        ts = float(data.get("ts") or data.get("t", time.time() * 1000)) / 1000
        message = OrderBookMessage(
            OrderBookMessageType.DIFF,
            {
                "trading_pair": trading_pair,
                "update_id": ts,
                "bids": data.get("bids") or data.get("b", []),
                "asks": data.get("asks") or data.get("a", []),
            },
            ts,
        )
        message_queue.put_nowait(message)

    async def _parse_order_book_snapshot_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        await self._parse_order_book_diff_message(raw_message, message_queue)

    def _channel_originating_message(self, event_message: Dict[str, Any]) -> str:
        channel = event_message.get("channel", "")
        if channel.startswith("trades."):
            return self._trade_messages_queue_key
        if channel.startswith("depth."):
            return self._diff_messages_queue_key
        return ""
