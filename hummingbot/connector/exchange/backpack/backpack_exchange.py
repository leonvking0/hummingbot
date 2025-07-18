import asyncio
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from hummingbot.connector.exchange.backpack import (
    backpack_constants as CONSTANTS,
    backpack_utils as utils,
    backpack_web_utils as web_utils
)
from hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source import BackpackAPIOrderBookDataSource
from hummingbot.connector.exchange.backpack.backpack_auth import BackpackAuth
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.connector.utils import get_new_client_order_id
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.data_type.common import OrderType, TradeType
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


class BackpackExchange(ExchangePyBase):
    """
    Backpack Exchange connector for Hummingbot
    Currently implements public API endpoints only
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
        
        super().__init__(client_config_map)

    @property
    def authenticator(self) -> AuthBase:
        """
        Return the authenticator for the exchange
        """
        if not hasattr(self, "_auth"):
            self._auth = None
        
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
            api_factory=self._web_assistants_factory,
            domain=self._domain
        )

    def _create_user_stream_data_source(self) -> UserStreamTrackerDataSource:
        """Create user stream data source"""
        # Not implemented for public API only
        return None
    
    def _create_user_stream_tracker(self):
        """
        Create user stream tracker
        For public API only implementation, we return None
        """
        return None

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
        """Update account balances from the exchange"""
        try:
            # Query capital/balances endpoint
            response = await self._api_get(
                path_url=CONSTANTS.BALANCES_PATH_URL,
                is_auth_required=True
            )
            
            # Update available and total balances
            for balance_data in response:
                asset = balance_data.get("symbol", "")
                available = Decimal(str(balance_data.get("available", "0")))
                locked = Decimal(str(balance_data.get("locked", "0"))) 
                total = available + locked
                
                self._account_available_balances[asset] = available
                self._account_balances[asset] = total
                
        except Exception as e:
            self.logger().error(
                f"Error updating balances. Error: {str(e)}",
                exc_info=True
            )
            raise

    async def _place_order(self,
                          order_id: str,
                          trading_pair: str,
                          amount: Decimal,
                          trade_type: TradeType,
                          order_type: OrderType,
                          price: Decimal,
                          **kwargs) -> str:
        """
        Place an order on the exchange
        
        :param order_id: Client order ID
        :param trading_pair: Trading pair
        :param amount: Order amount
        :param trade_type: Buy or Sell
        :param order_type: Limit or Market
        :param price: Order price (ignored for market orders)
        :return: Exchange order ID
        """
        try:
            # Convert trading pair to exchange format
            exchange_symbol = utils.convert_to_exchange_trading_pair(trading_pair)
            
            # Build order request payload
            order_data = {
                "symbol": exchange_symbol,
                "side": CONSTANTS.TRADE_TYPE_MAP[trade_type],
                "orderType": CONSTANTS.ORDER_TYPE_MAP[order_type],
                "quantity": str(amount),
            }
            
            # Add price for limit orders
            if order_type == OrderType.LIMIT:
                order_data["price"] = str(price)
            
            # Add optional parameters
            if "time_in_force" in kwargs:
                order_data["timeInForce"] = kwargs["time_in_force"]
            else:
                order_data["timeInForce"] = CONSTANTS.DEFAULT_TIME_IN_FORCE
                
            # Add client ID if we can fit it (Backpack uses uint32)
            try:
                # Extract numeric part from order_id if it contains prefix
                numeric_id = order_id.split("-")[-1] if "-" in order_id else order_id
                # Try to convert to int and check if it fits in uint32
                client_id = int(numeric_id)
                if 0 <= client_id <= 4294967295:  # uint32 max
                    order_data["clientId"] = client_id
            except (ValueError, OverflowError):
                # If conversion fails, skip client ID
                pass
            
            # Add any additional parameters from kwargs
            if "post_only" in kwargs and kwargs["post_only"]:
                order_data["postOnly"] = True
                
            # Send order to exchange
            response = await self._api_post(
                path_url=CONSTANTS.ORDER_PATH_URL,
                data=order_data,
                is_auth_required=True
            )
            
            # Extract exchange order ID from response
            exchange_order_id = str(response.get("id", ""))
            
            if not exchange_order_id:
                raise ValueError(f"No order ID returned from exchange: {response}")
                
            return exchange_order_id
            
        except Exception as e:
            self.logger().error(
                f"Error placing order {order_id}. Error: {str(e)}",
                exc_info=True
            )
            raise

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        """
        Cancel an order on the exchange
        
        :param order_id: Client order ID
        :param tracked_order: In-flight order to cancel
        """
        try:
            exchange_order_id = await tracked_order.get_exchange_order_id()
            
            # Build cancel request payload
            cancel_data = {
                "symbol": utils.convert_to_exchange_trading_pair(tracked_order.trading_pair),
                "orderId": exchange_order_id
            }
            
            # Alternatively, use clientId if available and exchange order ID is not yet known
            if not exchange_order_id and tracked_order.client_order_id:
                try:
                    # Extract numeric part from client order ID
                    numeric_id = tracked_order.client_order_id.split("-")[-1] if "-" in tracked_order.client_order_id else tracked_order.client_order_id
                    client_id = int(numeric_id)
                    if 0 <= client_id <= 4294967295:  # uint32 max
                        cancel_data = {
                            "symbol": utils.convert_to_exchange_trading_pair(tracked_order.trading_pair),
                            "clientId": client_id
                        }
                except (ValueError, OverflowError):
                    pass
            
            # Send cancel request
            response = await self._api_delete(
                path_url=CONSTANTS.ORDER_PATH_URL,
                data=cancel_data,
                is_auth_required=True
            )
            
            # Check if cancellation was successful
            if response.get("status") in ["Cancelled", "Filled"]:
                return True
                
            # Log any unexpected response
            self.logger().warning(
                f"Unexpected response when cancelling order {order_id}: {response}"
            )
            return False
            
        except Exception as e:
            self.logger().error(
                f"Error cancelling order {order_id}. Error: {str(e)}",
                exc_info=True
            )
            raise

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
                         data: Optional[Dict[str, Any]] = None,
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
            data=data,
            method=RESTMethod.DELETE,
            is_auth_required=is_auth_required
        )

    async def _update_order_status(self):
        """
        Update status of all in-flight orders by querying the exchange
        """
        # Get list of in-flight orders that need status updates
        tracked_orders = list(self.in_flight_orders.values())
        
        if not tracked_orders:
            return
            
        try:
            # Query all open orders from exchange
            open_orders = await self._api_get(
                path_url=CONSTANTS.ORDERS_PATH_URL,
                is_auth_required=True
            )
            
            # Create a map of order IDs for quick lookup
            open_order_ids = {str(order.get("id")): order for order in open_orders}
            open_client_ids = {}
            
            # Also map by client ID if available
            for order in open_orders:
                if "clientId" in order:
                    open_client_ids[str(order["clientId"])] = order
            
            # Update status of tracked orders
            for tracked_order in tracked_orders:
                exchange_order_id = await tracked_order.get_exchange_order_id()
                
                # Try to find order by exchange ID or client ID
                exchange_order = None
                if exchange_order_id and exchange_order_id in open_order_ids:
                    exchange_order = open_order_ids[exchange_order_id]
                elif tracked_order.client_order_id:
                    # Try to extract numeric client ID
                    try:
                        numeric_id = tracked_order.client_order_id.split("-")[-1]
                        if numeric_id in open_client_ids:
                            exchange_order = open_client_ids[numeric_id]
                    except:
                        pass
                
                if exchange_order:
                    # Update order status from exchange data
                    await self._process_order_update(tracked_order, exchange_order)
                else:
                    # Order not found in open orders - might be filled or cancelled
                    # Request specific order status
                    try:
                        order_update = await self._request_order_status(tracked_order)
                        if order_update:
                            tracked_order.update_with_order_update(order_update)
                    except Exception as e:
                        self.logger().warning(
                            f"Failed to get status for order {tracked_order.client_order_id}: {e}"
                        )
                        
        except Exception as e:
            self.logger().error(
                f"Error updating order status. Error: {str(e)}",
                exc_info=True
            )

    async def _user_stream_event_listener(self):
        """
        Listen to user stream events for real-time order and balance updates
        """
        # This would connect to WebSocket for real-time updates
        # For now, we'll rely on polling via _update_order_status
        # Full implementation would subscribe to account.orderUpdate stream
        pass

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        """
        Get all trade updates (fills) for a specific order
        
        :param order: The order to get fills for
        :return: List of trade updates
        """
        trade_updates = []
        
        try:
            exchange_order_id = await order.get_exchange_order_id()
            if not exchange_order_id:
                return trade_updates
                
            # Query fills for this order
            fills = await self._api_get(
                path_url=CONSTANTS.FILLS_PATH_URL,
                params={
                    "orderId": exchange_order_id,
                    "symbol": utils.convert_to_exchange_trading_pair(order.trading_pair)
                },
                is_auth_required=True
            )
            
            # Convert fills to TradeUpdate objects
            for fill in fills:
                trade_id = str(fill.get("tradeId", fill.get("id", "")))
                if not trade_id:
                    continue
                    
                trade_update = TradeUpdate(
                    trade_id=trade_id,
                    client_order_id=order.client_order_id,
                    exchange_order_id=exchange_order_id,
                    trading_pair=order.trading_pair,
                    fill_timestamp=float(fill.get("timestamp", 0)) / 1000.0,  # Convert ms to seconds
                    fill_price=Decimal(str(fill.get("price", "0"))),
                    fill_base_amount=Decimal(str(fill.get("quantity", "0"))),
                    fill_quote_amount=Decimal(str(fill.get("price", "0"))) * Decimal(str(fill.get("quantity", "0"))),
                    fee=self._get_trade_fee_from_fill(fill),
                )
                trade_updates.append(trade_update)
                
        except Exception as e:
            self.logger().error(
                f"Error getting trade updates for order {order.client_order_id}. Error: {str(e)}",
                exc_info=True
            )
            
        return trade_updates

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        """
        Request the current status of a specific order from the exchange
        
        :param tracked_order: The order to get status for
        :return: OrderUpdate with current status
        """
        try:
            exchange_order_id = await tracked_order.get_exchange_order_id()
            
            # Build query parameters
            params = {}
            if exchange_order_id:
                params["orderId"] = exchange_order_id
            else:
                # Try using client ID
                try:
                    numeric_id = tracked_order.client_order_id.split("-")[-1]
                    client_id = int(numeric_id)
                    if 0 <= client_id <= 4294967295:
                        params["clientId"] = client_id
                except:
                    raise ValueError("No valid order ID available for status query")
            
            # Query order status
            response = await self._api_get(
                path_url=CONSTANTS.ORDER_PATH_URL,
                params=params,
                is_auth_required=True
            )
            
            # Convert response to OrderUpdate
            return self._create_order_update_from_exchange_order(response, tracked_order)
            
        except Exception as e:
            self.logger().error(
                f"Error requesting order status for {tracked_order.client_order_id}. Error: {str(e)}",
                exc_info=True
            )
            raise

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
    
    def _create_order_update_from_exchange_order(self, order_data: Dict[str, Any], tracked_order: InFlightOrder) -> OrderUpdate:
        """
        Create an OrderUpdate object from exchange order data
        
        :param order_data: Order data from exchange
        :param tracked_order: The tracked order
        :return: OrderUpdate object
        """
        # Map exchange status to OrderState
        exchange_status = order_data.get("status", "")
        new_state = CONSTANTS.ORDER_STATE_MAP.get(exchange_status, OrderState.OPEN)
        
        # Create OrderUpdate
        order_update = OrderUpdate(
            trading_pair=tracked_order.trading_pair,
            update_timestamp=time.time(),
            new_state=new_state,
            client_order_id=tracked_order.client_order_id,
            exchange_order_id=str(order_data.get("id", "")),
        )
        
        return order_update
    
    async def _process_order_update(self, tracked_order: InFlightOrder, order_data: Dict[str, Any]):
        """
        Process an order update from exchange data
        
        :param tracked_order: The tracked order to update
        :param order_data: Order data from exchange
        """
        order_update = self._create_order_update_from_exchange_order(order_data, tracked_order)
        tracked_order.update_with_order_update(order_update)
        
        # If order is filled, get trade updates
        if order_update.new_state == OrderState.FILLED:
            trade_updates = await self._all_trade_updates_for_order(tracked_order)
            for trade_update in trade_updates:
                tracked_order.update_with_trade_update(trade_update)
    
    def _get_trade_fee_from_fill(self, fill_data: Dict[str, Any]) -> TradeFeeBase:
        """
        Extract trade fee information from a fill
        
        :param fill_data: Fill data from exchange
        :return: TradeFeeBase object
        """
        fee_amount = Decimal(str(fill_data.get("fee", "0")))
        fee_asset = fill_data.get("feeSymbol", "")
        
        if fee_amount > 0 and fee_asset:
            return TradeFeeBase.new_spot_fee(
                fee_schema=self.trade_fee_schema(),
                trade_type=TradeType.BUY if fill_data.get("side") == "Bid" else TradeType.SELL,
                percent_token=fee_asset,
                flat_fees=[TokenAmount(amount=fee_amount, token=fee_asset)]
            )
        else:
            # Return default fee if no fee info available
            return TradeFeeBase.new_spot_fee(
                fee_schema=self.trade_fee_schema(),
                trade_type=TradeType.BUY if fill_data.get("side") == "Bid" else TradeType.SELL,
            )

    def _is_order_not_found_during_cancelation_error(self, cancelation_exception: Exception) -> bool:
        """
        Check if the exception during order cancellation indicates that the order was not found.
        
        Based on Backpack API error codes:
        - INVALID_ORDER: The order is invalid (doesn't exist or wrong format)
        - RESOURCE_NOT_FOUND: The requested resource was not found
        """
        error_message = str(cancelation_exception).upper()
        
        # Check for specific Backpack error codes
        return (
            "INVALID_ORDER" in error_message or
            "RESOURCE_NOT_FOUND" in error_message or
            "ORDER NOT FOUND" in error_message or
            "UNKNOWN ORDER" in error_message
        )

    def _is_order_not_found_during_status_update_error(self, status_update_exception: Exception) -> bool:
        """
        Check if the exception during order status update indicates that the order was not found.
        
        Based on Backpack API error codes:
        - INVALID_ORDER: The order is invalid (doesn't exist or wrong format)
        - RESOURCE_NOT_FOUND: The requested resource was not found
        """
        error_message = str(status_update_exception).upper()
        
        # Check for specific Backpack error codes
        return (
            "INVALID_ORDER" in error_message or
            "RESOURCE_NOT_FOUND" in error_message or
            "ORDER NOT FOUND" in error_message or
            "UNKNOWN ORDER" in error_message or
            "ORDER DOES NOT EXIST" in error_message
        )

    async def _update_trading_fees(self):
        """
        Update trading fees from the exchange.
        
        For Backpack Exchange, since we're implementing public API only,
        we'll use default fees. In a full implementation with private API access,
        this would fetch the actual fee structure based on the user's tier.
        """
        # Default fee structure for Backpack Exchange
        # Maker: 0.02%, Taker: 0.04%
        # These are example values - actual fees should be fetched from the exchange
        pass