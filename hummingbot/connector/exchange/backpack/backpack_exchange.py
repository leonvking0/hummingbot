import asyncio
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set

from hummingbot.connector.exchange.backpack import (
    backpack_constants as CONSTANTS,
    backpack_utils as utils,
    backpack_web_utils as web_utils
)
from hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source import BackpackAPIOrderBookDataSource
from hummingbot.connector.exchange.backpack.backpack_auth import BackpackAuth
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory


class BackpackExchange(ExchangePyBase):
    """
    Backpack Exchange connector for Hummingbot
    Currently implements public API endpoints only
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        trading_pairs: Optional[List[str]] = None,
        trading_required: bool = False,
        domain: str = CONSTANTS.DEFAULT_DOMAIN,
    ):
        self._api_key = api_key
        self._api_secret = api_secret
        self._domain = domain
        self._trading_pairs = trading_pairs or []
        self._trading_required = trading_required
        
        super().__init__()

    @property
    def authenticator(self) -> AuthBase:
        """
        Return the authenticator for the exchange
        """
        if self._auth is None and self._api_key and self._api_secret:
            self._auth = BackpackAuth(
                api_key=self._api_key,
                api_secret=self._api_secret
            )
        return self._auth

    @property
    def name(self) -> str:
        """Exchange name"""
        return CONSTANTS.EXCHANGE_NAME

    @property
    def rate_limits_rules(self):
        """Rate limit rules"""
        return CONSTANTS.RATE_LIMITS

    @property
    def domain(self) -> str:
        """Exchange domain"""
        return self._domain

    @property
    def client_order_id_max_length(self) -> int:
        """Maximum length of client order id"""
        # Backpack uses uint32 for client order ID
        return 10  # Reasonable length for numeric ID as string

    @property
    def client_order_id_prefix(self) -> str:
        """Prefix for client order id"""
        return ""  # No prefix needed for Backpack

    @property
    def trading_rules_request_path(self) -> str:
        """API path for trading rules"""
        return CONSTANTS.MARKETS_PATH_URL

    @property
    def trading_pairs_request_path(self) -> str:
        """API path for trading pairs"""
        return CONSTANTS.MARKETS_PATH_URL

    @property
    def check_network_request_path(self) -> str:
        """API path for network check"""
        return CONSTANTS.MARKETS_PATH_URL

    @property
    def trading_pairs(self) -> List[str]:
        """List of trading pairs"""
        return self._trading_pairs

    @property
    def is_cancel_request_in_exchange_synchronous(self) -> bool:
        """Whether cancel requests are synchronous"""
        return False

    @property
    def is_trading_required(self) -> bool:
        """Whether trading is required"""
        return self._trading_required

    def supported_order_types(self) -> List[OrderType]:
        """Supported order types"""
        return [OrderType.LIMIT, OrderType.MARKET]

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception) -> bool:
        """Check if exception is related to time synchronization"""
        # Implement based on Backpack's specific error messages
        error_message = str(request_exception).lower()
        return "timestamp" in error_message or "window" in error_message

    def _create_web_assistants_factory(self) -> WebAssistantsFactory:
        """Create web assistants factory"""
        return web_utils.build_api_factory(
            throttler=self._throttler,
            auth=self._auth
        )

    def _create_order_book_data_source(self) -> OrderBookTrackerDataSource:
        """Create order book data source"""
        return BackpackAPIOrderBookDataSource(
            trading_pairs=self._trading_pairs,
            throttler=self._throttler,
            api_factory=self._api_factory,
            domain=self._domain
        )

    def _create_user_stream_data_source(self) -> UserStreamTrackerDataSource:
        """Create user stream data source"""
        # Not implemented for public API only
        raise NotImplementedError("User stream not implemented for public API only")

    def _get_fee(self,
                 base_currency: str,
                 quote_currency: str,
                 order_type: OrderType,
                 order_side: TradeType,
                 amount: Decimal,
                 price: Decimal = Decimal("0"),
                 is_maker: Optional[bool] = None) -> utils.TradeFeeBase:
        """Get trading fee"""
        # Default fee structure for Backpack
        # Actual fees should be fetched from the exchange
        is_maker = is_maker or (order_type == OrderType.LIMIT)
        return utils.parse_trade_fee({}, order_side, is_maker)

    async def _update_trading_rules(self):
        """Update trading rules from the exchange"""
        try:
            markets = await self._api_get(
                path_url=self.trading_rules_request_path,
                is_auth_required=False
            )
            
            trading_rules_list = []
            for market in markets:
                try:
                    if market.get("status") != "ONLINE":
                        continue
                        
                    exchange_symbol = market.get("symbol", "")
                    trading_pair = utils.convert_from_exchange_trading_pair(exchange_symbol)
                    
                    filters = market.get("filters", {})
                    price_filter = filters.get("price", {})
                    quantity_filter = filters.get("quantity", {})
                    
                    trading_rule = TradingRule(
                        trading_pair=trading_pair,
                        min_order_size=Decimal(str(quantity_filter.get("minQuantity", "0.00000001"))),
                        max_order_size=Decimal(str(quantity_filter.get("maxQuantity", "999999999"))),
                        min_price_increment=Decimal(str(price_filter.get("tickSize", "0.00000001"))),
                        min_base_amount_increment=Decimal(str(quantity_filter.get("stepSize", "0.00000001"))),
                        min_quote_amount_increment=Decimal(str(price_filter.get("tickSize", "0.00000001"))),
                        min_notional_size=Decimal("0"),  # Not provided by Backpack
                        min_order_value=Decimal("0"),  # Not provided by Backpack
                        supports_limit_orders=True,
                        supports_market_orders=True,
                    )
                    
                    trading_rules_list.append(trading_rule)
                    
                except Exception as e:
                    self.logger().error(
                        f"Error parsing trading rule for {market}. Error: {str(e)}",
                        exc_info=True
                    )
                    
            self._trading_rules.clear()
            for trading_rule in trading_rules_list:
                self._trading_rules[trading_rule.trading_pair] = trading_rule
                
        except Exception as e:
            self.logger().error(
                f"Error updating trading rules. Error: {str(e)}",
                exc_info=True
            )

    async def _update_balances(self):
        """Update account balances"""
        # Not implemented for public API only
        pass

    async def _place_order(self,
                          order_id: str,
                          trading_pair: str,
                          amount: Decimal,
                          trade_type: TradeType,
                          order_type: OrderType,
                          price: Decimal,
                          **kwargs) -> str:
        """Place an order"""
        # Not implemented for public API only
        raise NotImplementedError("Order placement not implemented for public API only")

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        """Cancel an order"""
        # Not implemented for public API only
        raise NotImplementedError("Order cancellation not implemented for public API only")

    async def _format_trading_rules(self, exchange_info_dict: Dict[str, Any]) -> List[TradingRule]:
        """Format trading rules from exchange info"""
        # This method is called by the base class but we handle it in _update_trading_rules
        return []

    async def _api_get(self,
                      path_url: str,
                      params: Optional[Dict[str, Any]] = None,
                      is_auth_required: bool = False,
                      limit_id: Optional[str] = None) -> Any:
        """Execute GET request"""
        rest_assistant = await self._web_assistants_factory.get_rest_assistant()
        
        if is_auth_required:
            url = web_utils.private_rest_url(path_url, self._domain)
        else:
            url = web_utils.public_rest_url(path_url, self._domain)
            
        return await rest_assistant.execute_request(
            url=url,
            throttler_limit_id=limit_id or path_url,
            params=params,
            method=RESTMethod.GET,
            is_auth_required=is_auth_required
        )

    async def _api_post(self,
                       path_url: str,
                       data: Optional[Dict[str, Any]] = None,
                       is_auth_required: bool = False,
                       limit_id: Optional[str] = None) -> Any:
        """Execute POST request"""
        rest_assistant = await self._web_assistants_factory.get_rest_assistant()
        
        if is_auth_required:
            url = web_utils.private_rest_url(path_url, self._domain)
        else:
            url = web_utils.public_rest_url(path_url, self._domain)
            
        return await rest_assistant.execute_request(
            url=url,
            throttler_limit_id=limit_id or path_url,
            data=data,
            method=RESTMethod.POST,
            is_auth_required=is_auth_required
        )

    async def _api_delete(self,
                         path_url: str,
                         params: Optional[Dict[str, Any]] = None,
                         is_auth_required: bool = False,
                         limit_id: Optional[str] = None) -> Any:
        """Execute DELETE request"""
        rest_assistant = await self._web_assistants_factory.get_rest_assistant()
        
        if is_auth_required:
            url = web_utils.private_rest_url(path_url, self._domain)
        else:
            url = web_utils.public_rest_url(path_url, self._domain)
            
        return await rest_assistant.execute_request(
            url=url,
            throttler_limit_id=limit_id or path_url,
            params=params,
            method=RESTMethod.DELETE,
            is_auth_required=is_auth_required
        )

    async def _update_order_status(self):
        """Update order status"""
        # Not implemented for public API only
        pass

    async def _user_stream_event_listener(self):
        """Listen to user stream events"""
        # Not implemented for public API only
        pass

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[Dict[str, Any]]:
        """Get all trade updates for an order"""
        # Not implemented for public API only
        return []

    async def _request_order_status(self, tracked_order: InFlightOrder) -> Dict[str, Any]:
        """Request order status"""
        # Not implemented for public API only
        return {}

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: Dict[str, Any]):
        """Initialize trading pair symbols"""
        # Not needed for Backpack
        pass

    async def _get_last_traded_price(self, trading_pair: str) -> float:
        """Get last traded price for a trading pair"""
        exchange_symbol = utils.convert_to_exchange_trading_pair(trading_pair)
        
        ticker = await self._api_get(
            path_url=CONSTANTS.TICKER_PATH_URL,
            params={"symbol": exchange_symbol},
            is_auth_required=False
        )
        
        return float(ticker.get("lastPrice", 0))