import asyncio
import json
from test.isolated_asyncio_wrapper_test_case import IsolatedAsyncioWrapperTestCase
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.connector.exchange.backpack.backpack_api_user_stream_data_source import (
    BackpackAPIUserStreamDataSource,
)
from hummingbot.connector.exchange.backpack.backpack_auth import BackpackAuth
from hummingbot.connector.test_support.network_mocking_assistant import NetworkMockingAssistant
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory


class BackpackAPIUserStreamDataSourceTests(IsolatedAsyncioWrapperTestCase):
    level = 0

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.trading_pair = "BTC-USDT"

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.log_records = []
        self.listening_task: Optional[asyncio.Task] = None
        self.mocking_assistant = NetworkMockingAssistant()

        self.throttler = AsyncThrottler(rate_limits=CONSTANTS.RATE_LIMITS)
        self.api_factory = WebAssistantsFactory(throttler=self.throttler)
        self.auth = BackpackAuth(api_key="key", secret_key="secret", time_provider=MagicMock())

        self.data_source = BackpackAPIUserStreamDataSource(
            auth=self.auth,
            trading_pairs=[self.trading_pair],
            connector=MagicMock(),
            api_factory=self.api_factory,
        )

        self.data_source.logger().setLevel(1)
        self.data_source.logger().addHandler(self)

    def tearDown(self) -> None:
        self.listening_task and self.listening_task.cancel()
        super().tearDown()

    def handle(self, record):
        self.log_records.append(record)

    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    @patch("hummingbot.connector.exchange.backpack.backpack_auth.BackpackAuth.ws_authenticate", new_callable=AsyncMock)
    async def test_listen_for_user_stream_subscribes_to_channels(self, ws_auth_mock, ws_connect_mock):
        ws_connect_mock.return_value = self.mocking_assistant.create_websocket_mock()

        async def auth_side_effect(request):
            request.payload = {"op": "login", "args": ["k", "1", "1", "sig"]}
            return request

        ws_auth_mock.side_effect = auth_side_effect

        self.mocking_assistant.add_websocket_aiohttp_message(
            websocket_mock=ws_connect_mock.return_value, message=json.dumps({})
        )

        self.data_source._sleep = AsyncMock(side_effect=asyncio.CancelledError())
        output_queue = asyncio.Queue()

        with self.assertRaises(asyncio.CancelledError):
            self.listening_task = self.local_event_loop.create_task(
                self.data_source.listen_for_user_stream(output_queue)
            )
            await self.mocking_assistant.run_until_all_aiohttp_messages_delivered(ws_connect_mock.return_value)
            await self.listening_task

        sent_messages = self.mocking_assistant.json_messages_sent_through_websocket(
            websocket_mock=ws_connect_mock.return_value
        )

        self.assertEqual(3, len(sent_messages))
        self.assertIn({"op": "subscribe", "channel": "orders"}, sent_messages)
        self.assertIn({"op": "subscribe", "channel": "balances"}, sent_messages)
        self.assertTrue(any(
            record.getMessage() == "Subscribed to private orders and balances channels..." for record in self.log_records
        ))

    async def test_process_event_message_adds_messages_to_queue(self):
        queue: asyncio.Queue = asyncio.Queue()
        ws = MagicMock()
        await self.data_source._process_event_message({"channel": "orders", "data": {"id": 1}}, queue, ws)
        await self.data_source._process_event_message({"channel": "balances", "data": {"BTC": "1"}}, queue, ws)
        self.assertEqual(2, queue.qsize())

    async def test_process_event_message_responds_to_ping(self):
        queue: asyncio.Queue = asyncio.Queue()
        ws = MagicMock()
        await self.data_source._process_event_message({"type": "ping"}, queue, ws)
        ws.send.assert_called()
        self.assertEqual(0, queue.qsize())
