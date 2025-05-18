import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from bidict import bidict

from hummingbot.connector.constants import s_decimal_0, s_decimal_NaN
from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS, backpack_web_utils as web_utils
from hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source import BackpackAPIOrderBookDataSource
from hummingbot.connector.exchange.backpack.backpack_api_user_stream_data_source import BackpackAPIUserStreamDataSource
from hummingbot.connector.exchange.backpack.backpack_auth import BackpackAuth
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.connector.utils import combine_to_hb_trading_pair
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState, OrderUpdate
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.utils.estimate_fee import build_trade_fee
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
        self._account_balances = {}
        self._account_available_balances = {}
        self._trading_pair_symbol_map = {}
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

    @property
    def current_timestamp(self) -> float:
        return self._time_synchronizer.time()

    @property
    def available_balances(self) -> Dict[str, Decimal]:
        return self._account_available_balances

    def get_balance(self, currency: str) -> Decimal:
        return self._account_balances.get(currency, s_decimal_0)

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
        return BackpackAPIUserStreamDataSource(
            auth=self._auth,
            trading_pairs=self._trading_pairs or [],
            connector=self,
            api_factory=self._web_assistants_factory,
            domain=self.domain,
        )

    def _create_user_stream_tracker(self):  # pragma: no cover - not implemented yet
        return None

    def _create_user_stream_tracker_task(self):  # pragma: no cover - not implemented yet
        return None

    def _is_user_stream_initialized(self):
        return True

    def _set_order_book_tracker(self, tracker):
        self._order_book_tracker = tracker

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: Dict[str, Any]):
        mapping = bidict()
        markets = []

        # Handle case where exchange_info is a list
        if isinstance(exchange_info, list):
            markets = exchange_info
        else:
            # Original behavior for dictionary response
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

    async def _get_last_traded_price(self, trading_pair: str) -> Decimal:
        params = {"symbol": await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)}
        resp = await self._api_get(path_url=CONSTANTS.TRADES_PATH_URL, params=params)
        trades = resp.get("data") or resp.get("trades") or resp
        if isinstance(trades, list) and len(trades) > 0:
            price = Decimal(str(trades[0].get("p") or trades[0].get("price")))
            return price
        return s_decimal_NaN

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
                "price": Decimal(str(trade.get("p") or trade.get("price"))),
                "amount": Decimal(str(trade.get("q") or trade.get("size"))),
                "timestamp": Decimal(str(trade.get("ts") or trade.get("t"))) / Decimal("1000"),
                "side": str(trade.get("side", "buy")).lower(),
            })
        return parsed_trades

    async def _place_order(
        self,
        order_id: str,
        trading_pair: str,
        amount: Decimal,
        trade_type: TradeType,
        order_type: OrderType,
        price: Decimal,
        **kwargs,
    ) -> Tuple[str, Decimal]:
        side = "buy" if trade_type is TradeType.BUY else "sell"
        type_str = "limit" if order_type.is_limit_type() else "market"
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
        data = {
            "clientOrderId": order_id,
            "symbol": symbol,
            "side": side,
            "type": type_str,
            "size": f"{amount:f}",
        }
        if order_type.is_limit_type():
            data["price"] = f"{price:f}"

        result = await self._api_post(
            path_url=CONSTANTS.ORDERS_PATH_URL,
            data=data,
            is_auth_required=True,
        )

        exchange_id = str(
            result.get("order_id")
            or result.get("id")
            or result.get("data", {}).get("order_id")
            or result.get("data", {}).get("id")
        )
        ts = Decimal(str(
            result.get("ts") or result.get("timestamp") or result.get("data", {}).get("timestamp", 0)
        )) / Decimal("1000")
        return exchange_id, ts

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        exchange_order_id = await tracked_order.get_exchange_order_id()
        path_url = f"{CONSTANTS.ORDERS_PATH_URL}/{exchange_order_id}"
        result = await self._api_delete(path_url=path_url, is_auth_required=True)
        success = str(result.get("status") or result.get("result") or "").lower() in ("success", "ok", "")
        return success

    async def _all_trade_updates_for_order(self, order):
        return []

    async def _update_balances(self):
        response = await self._api_get(path_url=CONSTANTS.BALANCE_PATH_URL, is_auth_required=True)
        balances = response.get("balances") or response.get("data") or response

        local_assets = set(self._account_balances.keys())
        remote_assets = set()

        for entry in balances:
            asset = entry.get("asset") or entry.get("currency") or entry.get("token")
            available = Decimal(str(entry.get("available") or entry.get("free") or entry.get("availableBalance") or entry.get("available_balance") or 0))
            total = Decimal(str(entry.get("total") or entry.get("balance") or entry.get("totalBalance") or entry.get("walletBalance") or available))
            self._account_available_balances[asset] = available
            self._account_balances[asset] = total
            remote_assets.add(asset)

        for asset in local_assets.difference(remote_assets):
            self._account_available_balances.pop(asset, None)
            self._account_balances.pop(asset, None)

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        exchange_order_id = await tracked_order.get_exchange_order_id()
        path_url = f"{CONSTANTS.ORDERS_PATH_URL}/{exchange_order_id}"
        resp = await self._api_get(path_url=path_url, is_auth_required=True)

        status = str(resp.get("status") or resp.get("data", {}).get("status") or "").lower()
        state_map = {
            "new": OrderState.OPEN,
            "open": OrderState.OPEN,
            "pending": OrderState.PENDING_CREATE,
            "partially_filled": OrderState.PARTIALLY_FILLED,
            "filled": OrderState.FILLED,
            "canceled": OrderState.CANCELED,
            "cancelled": OrderState.CANCELED,
            "failed": OrderState.FAILED,
        }
        new_state = state_map.get(status, OrderState.OPEN)

        return OrderUpdate(
            client_order_id=tracked_order.client_order_id,
            exchange_order_id=exchange_order_id,
            trading_pair=tracked_order.trading_pair,
            update_timestamp=self.current_timestamp,
            new_state=new_state,
        )

    async def _format_trading_rules(self, exchange_info: Dict[str, Any]) -> List[TradingRule]:
        """Format the trading rules for the exchange."""
        trading_rules = []
        markets = exchange_info.get("markets") or exchange_info.get("data") or []

        for market in markets:
            try:
                trading_pair = await self.trading_pair_associated_to_exchange_symbol(
                    symbol=market.get("id") or market.get("symbol") or market.get("name"))

                # Extract or set default values for trading rules
                min_order_size = Decimal(str(market.get("minOrderSize", "0.0001")))
                min_price_increment = Decimal(str(market.get("tickSize", "0.00001")))
                min_base_amount_increment = Decimal(str(market.get("stepSize", "0.0001")))
                min_notional_size = Decimal(str(market.get("minNotional", "1")))

                trading_rules.append(
                    TradingRule(
                        trading_pair=trading_pair,
                        min_order_size=min_order_size,
                        min_price_increment=min_price_increment,
                        min_base_amount_increment=min_base_amount_increment,
                        min_notional_size=min_notional_size
                    )
                )
            except Exception:
                self.logger().exception(f"Error parsing trading rule for {market.get('id', 'unknown')}. Skipping.")

        return trading_rules

    def _trade_fee_schema(self) -> TradeFeeBase:
        return TradeFeeBase()  # Default zero fees

    def _get_fee(
        self,
        base_currency: str,
        quote_currency: str,
        order_type: OrderType,
        order_side: TradeType,
        amount: Decimal,
        price: Decimal = s_decimal_NaN,
        is_maker: Optional[bool] = None,
    ) -> TradeFeeBase:
        is_maker = is_maker or (order_type is OrderType.LIMIT_MAKER)
        return build_trade_fee(
            exchange=self.name,
            is_maker=is_maker,
            base_currency=base_currency,
            quote_currency=quote_currency,
            order_type=order_type,
            order_side=order_side,
            amount=amount,
            price=price,
        )

    def _is_order_not_found_during_cancelation_error(self, cancelation_exception: Exception) -> bool:
        return "not found" in str(cancelation_exception).lower()

    def _is_order_not_found_during_status_update_error(self, status_update_exception: Exception) -> bool:
        return "not found" in str(status_update_exception).lower()

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception):
        return "timestamp" in str(request_exception).lower()

    async def _api_request(
        self,
        path_url: str,
        overwrite_url: Optional[str] = None,
        method: RESTMethod = RESTMethod.GET,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        is_auth_required: bool = False,
        return_err: bool = False,
        limit_id: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute an HTTP request with exponential backoff on failures."""
        backoff_delay = 1
        last_exception = None
        for _ in range(3):
            try:
                result = await super()._api_request(
                    path_url=path_url,
                    overwrite_url=overwrite_url,
                    method=method,
                    params=params,
                    data=data,
                    is_auth_required=is_auth_required,
                    return_err=return_err,
                    limit_id=limit_id,
                    headers=headers,
                )

                if isinstance(result, dict) and "code" in result and result.get("code") not in (0, "0"):
                    err_code = int(result.get("code"))
                    err_message = result.get("msg") or result.get("message", "")
                    exc_name = CONSTANTS.ERROR_CODE_MAPPING.get(err_code)
                    if exc_name == "RateLimitError":
                        raise IOError(f"Rate limit exceeded ({err_message})")
                    elif exc_name == "AuthenticationError":
                        raise PermissionError(f"Authentication failed ({err_message})")
                    elif exc_name == "OrderNotFound":
                        raise IOError(f"Order not found ({err_message})")

                return result
            except Exception as request_exception:
                last_exception = request_exception
                self.logger().debug(f"Request failed: {request_exception}. Retrying in {backoff_delay}s")
                await self._sleep(backoff_delay)
                backoff_delay = min(backoff_delay * 2, 60)
        raise last_exception

    async def _update_trading_fees(self):
        return

    async def _user_stream_event_listener(self):
        async for event_message in self._iter_user_event_queue():
            try:
                channel = event_message.get("channel")
                if channel == "balances":
                    balances = event_message.get("data") or []
                    entries = balances if isinstance(balances, list) else [balances]
                    for entry in entries:
                        asset = entry.get("asset") or entry.get("currency") or entry.get("token")
                        if asset is None:
                            continue
                        available = Decimal(str(entry.get("available") or entry.get("free") or 0))
                        total = Decimal(str(entry.get("total") or entry.get("balance") or available))
                        self._account_available_balances[asset] = available
                        self._account_balances[asset] = total
                elif channel == "orders":
                    data = event_message.get("data") or {}
                    client_order_id = str(data.get("clientOrderId") or data.get("client_id") or "")
                    exchange_order_id = str(data.get("order_id") or data.get("id") or "")
                    tracked_order = self._order_tracker.all_updatable_orders.get(client_order_id)
                    if tracked_order is not None:
                        status = str(data.get("status") or "").lower()
                        state_map = {
                            "new": OrderState.OPEN,
                            "open": OrderState.OPEN,
                            "pending": OrderState.PENDING_CREATE,
                            "partially_filled": OrderState.PARTIALLY_FILLED,
                            "filled": OrderState.FILLED,
                            "canceled": OrderState.CANCELED,
                            "cancelled": OrderState.CANCELED,
                            "failed": OrderState.FAILED,
                        }
                        new_state = state_map.get(status, tracked_order.current_state)
                        order_update = OrderUpdate(
                            trading_pair=tracked_order.trading_pair,
                            update_timestamp=self.current_timestamp,
                            new_state=new_state,
                            client_order_id=client_order_id,
                            exchange_order_id=exchange_order_id,
                        )
                        self._order_tracker.process_order_update(order_update=order_update)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error("Unexpected error in user stream listener loop.", exc_info=True)
                await self._sleep(5.0)

    def _set_trading_pair_symbol_map(self, mapping: bidict):
        self._trading_pair_symbol_map = mapping

    async def exchange_symbol_associated_to_pair(self, trading_pair: str) -> str:
        if trading_pair not in self._trading_pair_symbol_map.inverse:
            raise ValueError(f"Trading pair {trading_pair} not supported by this connector.")
        return self._trading_pair_symbol_map.inverse[trading_pair]
