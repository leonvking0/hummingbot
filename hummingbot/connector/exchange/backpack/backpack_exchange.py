import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from bidict import bidict

from hummingbot.connector.constants import s_decimal_NaN
from hummingbot.connector.exchange.backpack import (
    backpack_constants as CONSTANTS,
    backpack_web_utils as web_utils,
)
from hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source import (
    BackpackAPIOrderBookDataSource,
)
from hummingbot.connector.exchange.backpack.backpack_auth import BackpackAuth
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.connector.utils import combine_to_hb_trading_pair
from hummingbot.core.data_type.common import OrderType
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

if TYPE_CHECKING:
    from hummingbot.client.config.config_helpers import ClientConfigAdapter


class BackpackExchange(ExchangePyBase):
    """Minimal Backpack exchange connector implementation."""

    web_utils = web_utils

    def __init__(
        self,
        client_config_map: "ClientConfigAdapter",
        backpack_api_key: str,
        backpack_secret_key: str,
        trading_pairs: Optional[List[str]] = None,
        trading_required: bool = True,
        domain: str = CONSTANTS.DEFAULT_DOMAIN,
    ):
        self._api_key = backpack_api_key
        self._secret_key = backpack_secret_key
        self._domain = domain
        self._trading_required = trading_required
        self._trading_pairs = trading_pairs
        super().__init__(client_config_map)

    @property
    def authenticator(self):
        return BackpackAuth(
            api_key=self._api_key,
            secret_key=self._secret_key,
            time_provider=self._time_synchronizer,
        )

    @property
    def name(self) -> str:
        return CONSTANTS.EXCHANGE_NAME

    @property
    def rate_limits_rules(self):
        return CONSTANTS.RATE_LIMITS

    @property
    def domain(self):
        return self._domain

    @property
    def client_order_id_max_length(self):
        return CONSTANTS.MAX_ORDER_ID_LEN

    @property
    def client_order_id_prefix(self):
        return CONSTANTS.HBOT_ORDER_ID_PREFIX

    @property
    def trading_rules_request_path(self):
        return CONSTANTS.MARKETS_PATH_URL

    @property
    def trading_pairs_request_path(self):
        return CONSTANTS.MARKETS_PATH_URL

    @property
    def check_network_request_path(self):
        return CONSTANTS.SERVER_TIME_PATH_URL

    @property
    def trading_pairs(self):
        return self._trading_pairs

    @property
    def is_cancel_request_in_exchange_synchronous(self) -> bool:
        return True

    @property
    def is_trading_required(self) -> bool:
        return self._trading_required

    def supported_order_types(self):
        return [OrderType.LIMIT, OrderType.LIMIT_MAKER, OrderType.MARKET]

    def _create_web_assistants_factory(self) -> WebAssistantsFactory:
        return web_utils.build_api_factory(
            throttler=self._throttler,
            time_synchronizer=self._time_synchronizer,
            auth=self._auth,
        )

    def _create_order_book_data_source(self) -> OrderBookTrackerDataSource:
        return BackpackAPIOrderBookDataSource(
            trading_pairs=self._trading_pairs,
            connector=self,
            api_factory=self._web_assistants_factory,
        )

    def _create_user_stream_data_source(self) -> UserStreamTrackerDataSource:
        raise NotImplementedError

    def _create_user_stream_tracker(self):  # pragma: no cover - not implemented yet
        return None

    def _create_user_stream_tracker_task(self):  # pragma: no cover - not implemented yet
        return None

    def _is_user_stream_initialized(self):
        return True

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: Dict[str, Any]):
        mapping = bidict()
        markets = exchange_info.get("markets") or exchange_info.get("data") or []
        for market in markets:
            symbol = market.get("id") or market.get("symbol") or market.get("name")
            base = market.get("baseAsset") or market.get("base") or market.get("base_currency")
            quote = market.get("quoteAsset") or market.get("quote") or market.get("quote_currency")
            if symbol and base and quote:
                mapping[symbol] = combine_to_hb_trading_pair(base=base, quote=quote)
        if not mapping and self._trading_pairs:
            for trading_pair in self._trading_pairs:
                base, quote = trading_pair.split("-")
                mapping[f"{base}_{quote}"] = trading_pair
        self._set_trading_pair_symbol_map(mapping)

    async def _get_last_traded_price(self, trading_pair: str) -> float:
        params = {"symbol": await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)}
        resp = await self._api_get(path_url=CONSTANTS.TRADES_PATH_URL, params=params)
        trades = resp.get("data") or resp.get("trades") or resp
        if isinstance(trades, list) and len(trades) > 0:
            price = float(trades[0].get("p") or trades[0].get("price"))
            return price
        return float("nan")

    async def fetch_trades(self, trading_pair: str, limit: int = 50) -> List[Dict[str, Any]]:
        params = {
            "symbol": await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair),
            "limit": limit,
        }
        resp = await self._api_get(path_url=CONSTANTS.TRADES_PATH_URL, params=params)
        trades = resp.get("data") or resp.get("trades") or []
        parsed_trades = []
        for trade in trades:
            parsed_trades.append({
                "price": float(trade.get("p") or trade.get("price")),
                "amount": float(trade.get("q") or trade.get("size")),
                "timestamp": float(trade.get("ts") or trade.get("t")) / 1000,
                "side": str(trade.get("side", "buy")).lower(),
            })
        return parsed_trades

    # Placeholder implementations for trading actions
    async def _place_order(self, *args, **kwargs):
        raise NotImplementedError

    async def _place_cancel(self, *args, **kwargs):
        raise NotImplementedError

    async def _all_trade_updates_for_order(self, order):
        return []

    async def _update_balances(self):
        pass

    async def _format_trading_rules(self, exchange_info: Dict[str, Any]) -> List[TradingRule]:
        return []

    def _trade_fee_schema(self) -> TradeFeeBase:
        return TradeFeeBase()  # Default zero fees
