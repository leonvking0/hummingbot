import asyncio
import base64
import logging
import time
from typing import Optional, List, TYPE_CHECKING

from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.connector.exchange.backpack import backpack_web_utils as web_utils
from hummingbot.connector.exchange.backpack.backpack_auth import BackpackAuth
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant
from hummingbot.logger import HummingbotLogger

if TYPE_CHECKING:
    from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange


class BackpackAPIUserStreamDataSource(UserStreamTrackerDataSource):
    """
    User stream data source for Backpack Exchange
    Handles WebSocket connection for order updates and other private streams
    """
    
    HEARTBEAT_TIME_INTERVAL = 60.0  # Backpack sends ping every 60s
    PING_TIMEOUT = 120.0  # Connection closed if no pong within 120s
    
    _logger: Optional[HummingbotLogger] = None

    def __init__(
        self,
        auth: BackpackAuth,
        trading_pairs: List[str],
        connector: 'BackpackExchange',
        api_factory: WebAssistantsFactory,
        domain: str = CONSTANTS.DEFAULT_DOMAIN
    ):
        super().__init__()
        self._auth = auth
        self._trading_pairs = trading_pairs
        self._connector = connector
        self._domain = domain
        self._api_factory = api_factory
        self._ws_assistant: Optional[WSAssistant] = None
        self._last_recv_time = 0

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    @property
    def last_recv_time(self) -> float:
        """
        Returns the time of the last received message
        """
        if self._ws_assistant:
            return self._ws_assistant.last_recv_time
        return self._last_recv_time

    async def listen_for_user_stream(self, output: asyncio.Queue):
        """
        Connects to the user private channel in the exchange using a websocket connection
        """
        while True:
            try:
                self.logger().info("Connecting to Backpack user stream WebSocket...")
                ws: WSAssistant = await self._connected_websocket_assistant()
                await self._subscribe_to_user_streams(ws)
                self.logger().info("Successfully subscribed to Backpack user streams")
                
                while True:
                    try:
                        await self._process_ws_messages(ws=ws, output=output)
                    except asyncio.TimeoutError:
                        # Expected behavior - WebSocket will handle ping/pong internally
                        continue
                        
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception(
                    "Unexpected error while listening to user stream. Retrying after 5 seconds..."
                )
            finally:
                # Clean up
                if ws:
                    await ws.disconnect()
                await self._sleep(5)

    async def _connected_websocket_assistant(self) -> WSAssistant:
        """
        Creates and connects to the WebSocket
        """
        ws: WSAssistant = await self._api_factory.get_ws_assistant()
        await ws.connect(
            ws_url=web_utils.wss_url(self._domain),
            ping_timeout=self.PING_TIMEOUT
        )
        return ws

    async def _subscribe_to_user_streams(self, ws: WSAssistant):
        """
        Subscribes to the user account order update stream
        """
        if not self._auth:
            raise ValueError("Authentication is required for user stream subscription")
            
        # Generate authentication signature
        timestamp = int(time.time() * 1000)
        window = CONSTANTS.DEFAULT_REQUEST_WINDOW
        
        # Create the signature message
        auth_message = f"instruction=subscribe&timestamp={timestamp}&window={window}"
        signature = self._auth.get_signature(auth_message)
        
        # Prepare subscription message
        subscribe_request = {
            "method": "SUBSCRIBE",
            "params": ["account.orderUpdate"],
            "signature": [
                self._auth.api_key,  # verifying key (public key)
                signature,           # signature
                str(timestamp),      # timestamp as string
                str(window)          # window as string
            ]
        }
        
        # Send subscription request
        await ws.send(WSJSONRequest(payload=subscribe_request))
        
        # Wait for subscription confirmation (typically first message)
        # Backpack doesn't send explicit subscription confirmation, 
        # so we'll just log and continue
        self.logger().debug(f"Sent subscription request: {subscribe_request['params']}")

    async def _process_ws_messages(self, ws: WSAssistant, output: asyncio.Queue):
        """
        Processes incoming WebSocket messages
        """
        async for ws_response in ws.iter_messages():
            try:
                data = ws_response.data
                
                if isinstance(data, dict):
                    # Check if it's a wrapped stream message
                    if "stream" in data and "data" in data:
                        stream_name = data["stream"]
                        stream_data = data["data"]
                        
                        if stream_name.startswith("account.orderUpdate"):
                            # Process order update
                            await self._process_order_update(stream_data, output)
                    else:
                        # Handle other message types (errors, etc.)
                        self.logger().debug(f"Received non-stream message: {data}")
                        
                # Update last received time
                self._last_recv_time = time.time()
                
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception("Failed to process WebSocket message")
                # Continue processing other messages

    async def _process_order_update(self, data: dict, output: asyncio.Queue):
        """
        Processes order update messages and adds them to the output queue
        """
        try:
            # Log the raw order update for debugging
            self.logger().debug(f"Processing order update: {data}")
            
            # Convert microseconds to milliseconds for consistency with Hummingbot
            if "E" in data:
                data["E"] = data["E"] / 1000  # Event time
            if "T" in data:
                data["T"] = data["T"] / 1000  # Engine timestamp
                
            # Add the update to the output queue
            output.put_nowait(data)
            
        except Exception:
            self.logger().exception(f"Failed to process order update: {data}")