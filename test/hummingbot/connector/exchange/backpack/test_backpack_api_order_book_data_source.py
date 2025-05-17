import asyncio
import json
import re
from test.isolated_asyncio_wrapper_test_case import IsolatedAsyncioWrapperTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from aioresponses import aioresponses

from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source import (
    BackpackAPIOrderBookDataSource,
)
from hummingbot.connector.test_support.network_mocking_assistant import NetworkMockingAssistant
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.data_type.order_book_message import OrderBookMessageType
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory


class BackpackAPIOrderBookDataSourceTests(IsolatedAsyncioWrapperTestCase):
    level = 0

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.trading_pair = "BTC-USDT"
        cls.ex_trading_pair = "BTC_USDT"

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.log_records = []
        self.listening_task = None
        self.mocking_assistant = NetworkMockingAssistant()

        # Add ORDER_BOOK_PATH_URL to rate limits for testing
        self.rate_limits = CONSTANTS.RATE_LIMITS.copy()
        self.rate_limits.append(
            CONSTANTS.RateLimit(limit_id=CONSTANTS.ORDER_BOOK_PATH_URL, limit=10, time_interval=1)
        )

        throttler = AsyncThrottler(self.rate_limits)
        self.api_factory = WebAssistantsFactory(throttler=throttler)

        self.connector = MagicMock()
        self.connector._web_assistants_factory = self.api_factory
        self.connector.get_last_traded_prices = AsyncMock(return_value={})
        self.connector.exchange_symbol_associated_to_pair = AsyncMock(return_value=self.ex_trading_pair)
        self.connector.trading_pair_associated_to_exchange_symbol = AsyncMock(return_value=self.trading_pair)

        self.data_source = BackpackAPIOrderBookDataSource(
            trading_pairs=[self.trading_pair],
            connector=self.connector,
            api_factory=self.api_factory,
        )

        self.data_source.logger().setLevel(1)
        self.data_source.logger().addHandler(self)

    def tearDown(self) -> None:
        self.listening_task and self.listening_task.cancel()
        super().tearDown()

    def handle(self, record):
        self.log_records.append(record)

    def _snapshot_response(self):
        return {
            "ts": 1700000000000,
            "bids": [["100", "1"]],
            "asks": [["101", "2"]],
        }

    @aioresponses()
    async def test_get_new_order_book_successful(self, mock_api):
        url = f"{CONSTANTS.REST_URL}{CONSTANTS.ORDER_BOOK_PATH_URL}"
        regex_url = re.compile(f"^{url}")
        resp = self._snapshot_response()
        mock_api.get(regex_url, body=json.dumps(resp))

        order_book = await self.data_source.get_new_order_book(self.trading_pair)

        self.assertEqual(resp["ts"] / 1000, order_book.snapshot_uid)
        self.assertEqual(100.0, list(order_book.bid_entries())[0].price)
        self.assertEqual(101.0, list(order_book.ask_entries())[0].price)

    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    async def test_listen_for_subscriptions_subscribes_to_channels(self, ws_connect_mock):
        ws_connect_mock.return_value = self.mocking_assistant.create_websocket_mock()

        self.mocking_assistant.add_websocket_aiohttp_message(
            websocket_mock=ws_connect_mock.return_value, message=json.dumps({})
        )
        self.mocking_assistant.add_websocket_aiohttp_message(
            websocket_mock=ws_connect_mock.return_value, message=json.dumps({})
        )

        self.listening_task = self.local_event_loop.create_task(self.data_source.listen_for_subscriptions())

        await self.mocking_assistant.run_until_all_aiohttp_messages_delivered(ws_connect_mock.return_value)

        sent_messages = self.mocking_assistant.json_messages_sent_through_websocket(ws_connect_mock.return_value)
        expected_depth = {"op": "subscribe", "channel": f"depth.{self.ex_trading_pair}"}
        expected_trade = {"op": "subscribe", "channel": f"trades.{self.ex_trading_pair}"}
        self.assertIn(expected_depth, sent_messages)
        self.assertIn(expected_trade, sent_messages)

    async def test_parse_order_book_diff_message(self):
        self.data_source._channel_associated_to_pair[f"depth.{self.ex_trading_pair}"] = self.trading_pair
        diff_event = {
            "channel": f"depth.{self.ex_trading_pair}",
            "data": {"ts": 1700000000000, "bids": [["100", "1"]], "asks": [["101", "2"]]},
        }
        queue: asyncio.Queue = asyncio.Queue()
        await self.data_source._parse_order_book_diff_message(diff_event, queue)
        msg = queue.get_nowait()
        self.assertEqual(OrderBookMessageType.DIFF, msg.type)
        self.assertEqual(1700000000, msg.update_id)
