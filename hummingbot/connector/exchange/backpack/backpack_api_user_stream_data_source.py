import asyncio
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.connector.exchange.backpack.backpack_auth import BackpackAuth
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant
from hummingbot.logger import HummingbotLogger

if TYPE_CHECKING:
    from .backpack_exchange import BackpackExchange


class BackpackAPIUserStreamDataSource(UserStreamTrackerDataSource):
    """User stream data source for Backpack exchange."""

    _logger: Optional[HummingbotLogger] = None

    def __init__(
        self,
        auth: BackpackAuth,
        trading_pairs: List[str],
        connector: "BackpackExchange",
        api_factory: WebAssistantsFactory,
        domain: str = CONSTANTS.DEFAULT_DOMAIN,
    ):
        super().__init__()
        self._auth: BackpackAuth = auth
        self._trading_pairs = trading_pairs
        self._connector = connector
        self._api_factory = api_factory
        self._domain = domain
        self._reconnect_delay = 1
        self._last_ws_message_sent_timestamp = 0

    async def _connected_websocket_assistant(self) -> WSAssistant:
        ws: WSAssistant = await self._api_factory.get_ws_assistant()
        await ws.connect(
            ws_url=CONSTANTS.WSS_PRIVATE_URL,
            ping_timeout=CONSTANTS.WS_HEARTBEAT_TIME_INTERVAL,
        )
        auth_request = WSJSONRequest(payload={}, is_auth_required=True)
        await self._auth.ws_authenticate(auth_request)
        await ws.send(auth_request)
        response = await ws.receive()
        message = response.data if response is not None else None
        if message is not None and message.get("success") is False:
            raise IOError(f"Private websocket connection authentication failed ({message})")
        self._reconnect_delay = 1
        return ws

    async def _subscribe_channels(self, websocket_assistant: WSAssistant):
        try:
            orders_payload = {"op": "subscribe", "channel": "orders"}
            balances_payload = {"op": "subscribe", "channel": "balances"}
            await websocket_assistant.send(WSJSONRequest(payload=orders_payload))
            await websocket_assistant.send(WSJSONRequest(payload=balances_payload))
            self.logger().info("Subscribed to private orders and balances channels...")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger().error(
                "Unexpected error occurred subscribing to user streams...",
                exc_info=True,
            )
            raise

    async def _process_websocket_messages(self, websocket_assistant: WSAssistant, queue: asyncio.Queue):
        async for ws_response in websocket_assistant.iter_messages():
            data = ws_response.data
            if data is not None:
                await self._process_event_message(
                    event_message=data, queue=queue, websocket_assistant=websocket_assistant
                )

    async def _process_event_message(
        self, event_message: Dict[str, Any], queue: asyncio.Queue, websocket_assistant: WSAssistant
    ):
        event_type = str(event_message.get("type") or event_message.get("event") or "")
        if event_type == "ping":
            pong_payload = {"op": "pong"}
            await websocket_assistant.send(WSJSONRequest(payload=pong_payload))
            return
        channel = event_message.get("channel")
        if channel in ("orders", "balances"):
            queue.put_nowait(event_message)

    async def _send_ping(self, websocket_assistant: WSAssistant):
        ping_payload = {"op": "ping"}
        await websocket_assistant.send(WSJSONRequest(payload=ping_payload))
        self._last_ws_message_sent_timestamp = self._time()

    async def _on_user_stream_interruption(self, websocket_assistant: Optional[WSAssistant]):
        await super()._on_user_stream_interruption(websocket_assistant=websocket_assistant)
        await self._sleep(self._reconnect_delay)
        self._reconnect_delay = min(self._reconnect_delay * 2, 60)

    def _time(self) -> float:
        return time.time()
