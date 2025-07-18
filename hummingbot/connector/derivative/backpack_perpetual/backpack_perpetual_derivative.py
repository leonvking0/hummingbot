import asyncio
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from hummingbot.connector.derivative.backpack_perpetual import (
    backpack_perpetual_constants as CONSTANTS,
    backpack_perpetual_utils as utils,
    backpack_perpetual_web_utils as web_utils
)
from hummingbot.connector.derivative.backpack_perpetual.backpack_perpetual_api_order_book_data_source import (
    BackpackPerpetualAPIOrderBookDataSource
)
from hummingbot.connector.derivative.backpack_perpetual.backpack_perpetual_auth import BackpackPerpetualAuth
from hummingbot.connector.derivative.position import Position
from hummingbot.connector.perpetual_derivative_py_base import PerpetualDerivativePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.data_type.common import OrderType, PositionAction, PositionMode, PositionSide, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import TokenAmount, TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

if TYPE_CHECKING:
    from hummingbot.client.config.config_helpers import ClientConfigAdapter


class BackpackPerpetualDerivative(PerpetualDerivativePyBase):
    """
    Backpack Perpetual Exchange connector for Hummingbot
    """

    def __init__(
        self,
        client_config_map: "ClientConfigAdapter",
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
        self._position_mode = PositionMode.ONEWAY  # Default to ONEWAY mode
        
        super().__init__(client_config_map)

    @property
    def authenticator(self) -> AuthBase:
        """
        Return the authenticator for the exchange
        """
        if not hasattr(self, "_auth"):
            self._auth = None
        
        if self._auth is None and self._api_key and self._api_secret:
            self._auth = BackpackPerpetualAuth(
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

    @property
    def funding_fee_poll_interval(self) -> int:
        """
        Funding fee poll interval in seconds
        """
        # Poll every 4 hours (half of funding interval)
        return CONSTANTS.FUNDING_RATE_INTERVAL_HOURS * 3600 // 2

    def supported_order_types(self) -> List[OrderType]:
        """Supported order types"""
        return [OrderType.LIMIT, OrderType.MARKET]

    def supported_position_modes(self) -> List[PositionMode]:
        """
        Supported position modes for this connector
        Backpack supports both ONEWAY and HEDGE modes
        """
        return [PositionMode.ONEWAY, PositionMode.HEDGE]

    def get_buy_collateral_token(self, trading_pair: str) -> str:
        """
        Get the collateral token for buy orders
        For perpetuals, it's typically the quote currency
        """
        _, quote = utils.split_trading_pair(trading_pair)
        return quote

    def get_sell_collateral_token(self, trading_pair: str) -> str:
        """
        Get the collateral token for sell orders
        For perpetuals, it's typically the quote currency
        """
        _, quote = utils.split_trading_pair(trading_pair)
        return quote

    def _create_web_assistants_factory(self) -> WebAssistantsFactory:
        """Create web assistants factory"""
        return web_utils.build_api_factory(
            throttler=self._throttler,
            auth=self._auth
        )

    def _create_order_book_data_source(self) -> OrderBookTrackerDataSource:
        """Create order book data source"""
        return BackpackPerpetualAPIOrderBookDataSource(
            trading_pairs=self._trading_pairs,
            throttler=self._throttler,
            api_factory=self._web_assistants_factory,
            domain=self._domain
        )

    def _get_fee(self,
                 base_currency: str,
                 quote_currency: str,
                 order_type: OrderType,
                 order_side: TradeType,
                 amount: Decimal,
                 price: Decimal = Decimal("0"),
                 is_maker: Optional[bool] = None) -> TradeFeeBase:
        """
        Get fee for the order
        """
        # For perpetuals, fees are usually in the quote currency
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
                    if not utils.is_exchange_information_valid(market):
                        continue
                        
                    exchange_symbol = market.get("symbol", "")
                    trading_pair = utils.convert_from_exchange_trading_pair(exchange_symbol)
                    
                    parsed_rules = utils.parse_trading_rule(market)
                    
                    trading_rule = TradingRule(
                        trading_pair=trading_pair,
                        min_order_size=parsed_rules["min_order_size"],
                        max_order_size=parsed_rules["max_order_size"],
                        min_price_increment=parsed_rules["min_price_increment"],
                        min_base_amount_increment=parsed_rules["min_base_amount_increment"],
                        min_quote_amount_increment=parsed_rules["min_quote_amount_increment"],
                        min_notional_size=parsed_rules["min_notional_size"],
                        min_order_value=Decimal("0"),  # Not provided by Backpack
                        supports_limit_orders=parsed_rules["supports_limit_orders"],
                        supports_market_orders=parsed_rules["supports_market_orders"],
                    )
                    
                    trading_rules_list.append(trading_rule)
                    
                except Exception as e:
                    self.logger().error(
                        f"Error parsing trading rule for {market.get('symbol', 'unknown')}. "
                        f"Error: {str(e)}. Market info: {market}",
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
        # This is a placeholder - implement when private API is ready
        self.logger().warning("Balance update not implemented for public API only")

    async def _update_positions(self):
        """
        Update positions from the exchange
        """
        # This is a placeholder - implement when private API is ready
        self.logger().warning("Position update not implemented for public API only")

    async def _update_order_status(self):
        """Update order status"""
        # This is a placeholder - implement when private API is ready
        self.logger().warning("Order status update not implemented for public API only")

    async def _place_order(self,
                          order_id: str,
                          trading_pair: str,
                          amount: Decimal,
                          trade_type: TradeType,
                          order_type: OrderType,
                          price: Optional[Decimal] = None,
                          position_action: PositionAction = PositionAction.OPEN,
                          **kwargs) -> Tuple[str, float]:
        """Place an order"""
        raise NotImplementedError("Order placement not implemented for public API only")

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        """Cancel an order"""
        raise NotImplementedError("Order cancellation not implemented for public API only")

    async def _format_trading_rules(self, exchange_info_dict: Dict[str, Any]) -> List[TradingRule]:
        """Format trading rules from exchange info"""
        # This method is called by the base class but we handle it in _update_trading_rules
        return []

    def _is_order_not_found_during_status_update_error(self, status_update_exception: Exception) -> bool:
        """
        Check if the error is due to order not found during status update
        """
        error_message = str(status_update_exception)
        return (
            "INVALID_ORDER" in error_message or
            "RESOURCE_NOT_FOUND" in error_message
        )

    def _is_order_not_found_during_cancelation_error(self, cancelation_exception: Exception) -> bool:
        """
        Check if the error is due to order not found during cancellation
        """
        error_message = str(cancelation_exception)
        return (
            "INVALID_ORDER" in error_message or
            "RESOURCE_NOT_FOUND" in error_message
        )

    async def _trading_pair_position_mode_set(self, mode: PositionMode, trading_pairs: List[str]) -> Tuple[bool, str]:
        """
        Set position mode for trading pairs
        """
        # This is a placeholder - implement when private API is ready
        self._position_mode = mode
        return True, ""

    async def _set_trading_pair_leverage(self, trading_pair: str, leverage: int) -> Tuple[bool, str]:
        """
        Set leverage for a trading pair
        """
        # This is a placeholder - implement when private API is ready
        return True, ""

    async def _fetch_last_fee_payment(self, trading_pair: str) -> Tuple[int, Decimal, Decimal]:
        """
        Fetch last funding fee payment for a trading pair
        Returns: (timestamp, funding_rate, payment_amount)
        """
        # This is a placeholder - implement when private API is ready
        return 0, Decimal("0"), Decimal("0")

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

    def _create_user_stream_data_source(self) -> Optional[UserStreamTrackerDataSource]:
        """
        Create user stream data source
        Returns None for public API only implementation
        """
        return None

    async def _user_stream_event_listener(self):
        """
        User stream event listener
        Does nothing for public API only implementation
        """
        pass

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception) -> bool:
        """
        Check if the request exception is related to time synchronization issues
        """
        error_message = str(request_exception).lower()
        # Check for common time-related errors
        return (
            "timestamp" in error_message or
            "time" in error_message and "sync" in error_message or
            "clock skew" in error_message
        )

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        """
        Fetch all trade updates for a specific order
        This is a placeholder for public API only implementation
        """
        # For public API only, we cannot fetch trade updates
        return []

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        """
        Request the status of a tracked order
        This is a placeholder for public API only implementation
        """
        # For public API only, we cannot fetch order status
        # Return a canceled status to avoid blocking the order tracker
        return OrderUpdate(
            trading_pair=tracked_order.trading_pair,
            update_timestamp=self.current_timestamp,
            new_state=OrderState.CANCELED,
            client_order_id=tracked_order.client_order_id,
        )

    async def _update_trading_fees(self):
        """
        Update trading fees from the exchange
        This is a placeholder for public API only implementation
        """
        # Trading fees would require authenticated API access
        # For now, we'll use default fees
        pass

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: Dict[str, Any]):
        """
        Initialize trading pair symbols from exchange info
        Maps exchange symbols to standard trading pair format
        """
        from bidict import bidict
        
        mapping = bidict()
        
        # For Backpack, the exchange info is a list of markets
        if isinstance(exchange_info, list):
            for market_info in exchange_info:
                exchange_symbol = market_info.get("symbol", "")
                if exchange_symbol:
                    trading_pair = utils.convert_from_exchange_trading_pair(exchange_symbol)
                    mapping[exchange_symbol] = trading_pair
        else:
            # Handle case where exchange_info might be a dict
            self.logger().warning(
                f"Unexpected exchange info format: {type(exchange_info)}. Expected list."
            )
        
        self._set_trading_pair_symbol_map(mapping)