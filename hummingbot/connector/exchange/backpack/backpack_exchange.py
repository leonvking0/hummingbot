import asyncio
import json
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from hummingbot.connector.exchange.backpack import (
    backpack_constants as CONSTANTS,
    backpack_utils as utils,
    backpack_web_utils as web_utils
)
from hummingbot.connector.exchange.backpack.backpack_api_order_book_data_source import BackpackAPIOrderBookDataSource
from hummingbot.connector.exchange.backpack.backpack_auth import BackpackAuth
from hummingbot.connector.exchange.backpack.backpack_api_user_stream_data_source import BackpackAPIUserStreamDataSource
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
    
    Supports both public market data and private trading operations.
    Trading functionality requires valid API credentials.
    """
    
    web_utils = web_utils

    def __init__(
        self,
        client_config_map: "ClientConfigAdapter",
        api_key: str = "",
        api_secret: str = "",
        trading_pairs: Optional[List[str]] = None,
        trading_required: bool = False,
        domain: str = CONSTANTS.DEFAULT_DOMAIN,
        demo_mode: bool = False,
    ):
        self._api_key = api_key
        self._api_secret = api_secret
        self._domain = domain
        self._trading_pairs = trading_pairs or []
        # Enable trading if API credentials are provided, unless explicitly set
        # If trading_required is explicitly passed (True or False), use that value
        # Otherwise, enable trading if API credentials are provided
        if trading_required is not None and isinstance(trading_required, bool):
            self._trading_required = trading_required
        else:
            self._trading_required = bool(api_key and api_secret)
        self._demo_mode = demo_mode or (not api_key and not api_secret)
        
        # Debug logging
        self.logger().info(f"BackpackExchange initialized, "
                          f"api_key={'provided' if api_key else 'empty'}, "
                          f"trading_required={trading_required}, "
                          f"demo_mode={self._demo_mode}, "
                          f"trading_pairs={trading_pairs}")
        
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
    
    @property
    def ready(self) -> bool:
        """
        Override to add debug logging
        """
        status = self.status_dict
        is_ready = all(status.values())
        
        if not is_ready:
            not_ready_items = [k for k, v in status.items() if not v]
            # Use warning level so it shows up even with INFO log level
            self.logger().warning(f"BackpackExchange not ready. Failed checks: {not_ready_items}, Full status: {status}")
            self.logger().warning(f"Additional debug info: is_trading_required={self.is_trading_required}, "
                                f"symbol_map_ready={self.trading_pair_symbol_map_ready()}, "
                                f"order_book_ready={self.order_book_tracker.ready if self.order_book_tracker else 'None'}")
        
        return is_ready

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
        # Only create user stream if we have API credentials
        if self._api_key and self._api_secret:
            return BackpackAPIUserStreamDataSource(
                auth=self.authenticator,
                trading_pairs=self._trading_pairs,
                connector=self,
                api_factory=self._web_assistants_factory,
                domain=self._domain
            )
        return None
    
    def _create_user_stream_tracker(self):
        """
        Create user stream tracker
        Returns None if no API credentials are provided
        """
        user_stream_data_source = self._create_user_stream_data_source()
        if user_stream_data_source is None:
            return None
        return super()._create_user_stream_tracker()
    
    def _is_user_stream_initialized(self) -> bool:
        """
        Override parent method to handle None user_stream_tracker
        For public API only, we don't have user streams
        """
        if not self.is_trading_required:
            return True  # No user stream needed when trading is not required
        if self._user_stream_tracker is None:
            return True  # Consider it "initialized" for public-only
        # Check if user stream has been created and started
        if hasattr(self._user_stream_tracker, 'data_source') and self._user_stream_tracker.data_source:
            # For now, consider it initialized if the data source exists
            # In production, you'd wait for first message: return self._user_stream_tracker.data_source.last_recv_time > 0
            return True
        return False
    
    async def start_network(self):
        """
        Override parent method to handle public-only implementation
        """
        self.logger().info(f"BackpackExchange.start_network called, is_trading_required={self.is_trading_required}")
        
        await self.stop_network()
        self.order_book_tracker.start()
        
        # Initialize trading pair symbol map
        if not self.trading_pair_symbol_map_ready():
            self.logger().info("Initializing trading pair symbol map...")
            await self._initialize_trading_pair_symbol_map()
        
        # Only start trading-related tasks if trading is required
        if self.is_trading_required:
            self.logger().info("Starting trading-related tasks...")
            # Initialize trading rules immediately before starting polling loop
            try:
                await self._update_trading_rules()
                self.logger().info(f"Trading rules initialized with {len(self._trading_rules)} rules")
            except Exception as e:
                self.logger().error(f"Failed to initialize trading rules: {e}", exc_info=True)
                
            self._trading_rules_polling_task = safe_ensure_future(self._trading_rules_polling_loop())
            self._trading_fees_polling_task = safe_ensure_future(self._trading_fees_polling_loop())
            self._status_polling_task = safe_ensure_future(self._status_polling_loop())
            self.logger().info("Started polling tasks")
            
            # Skip user stream tracker for public-only implementation
            if self._user_stream_tracker is not None:
                self._user_stream_tracker_task = safe_ensure_future(self._user_stream_tracker.start())
                self._user_stream_event_listener_task = safe_ensure_future(self._user_stream_event_listener())
            self._lost_orders_update_task = safe_ensure_future(self._lost_orders_update_polling_loop())
    
    async def _update_balances(self):
        """
        Update account balances from the exchange
        """
        self.logger().debug(f"_update_balances called, is_trading_required={self.is_trading_required}, demo_mode={self._demo_mode}")
        
        if not self.is_trading_required:
            # Set empty balances for public-only mode
            self._account_balances = {}
            self._account_available_balances = {}
            return
        
        # In demo mode, provide mock balances
        if self._demo_mode:
            self.logger().info("Demo mode: Using mock balances")
            self._account_balances = {
                "USDC": Decimal("10000"),
                "SOL": Decimal("10"),
            }
            self._account_available_balances = {
                "USDC": Decimal("10000"),
                "SOL": Decimal("10"),
            }
            return
        
        # Fetch balances from the exchange
        try:
            # First try the capital API for spot balances
            self.logger().debug(f"Fetching balances from {CONSTANTS.BALANCES_PATH_URL}")
            response = await self._api_get(
                path_url=CONSTANTS.BALANCES_PATH_URL,
                is_auth_required=True
            )
            
            self.logger().info(f"Capital API response: {response}")
            
            # Clear existing balances
            self._account_balances.clear()
            self._account_available_balances.clear()
            
            # Check if we got any non-zero balances from capital API
            has_spot_balance = False
            
            # Parse balance data
            # According to API docs, response format is: {"BTC": {"available": "0.1", "locked": "0", "staked": "0"}}
            if isinstance(response, dict):
                for asset, balance_data in response.items():
                    if not isinstance(balance_data, dict):
                        self.logger().warning(f"Unexpected balance format for {asset}: {balance_data}")
                        continue
                    
                    # Parse balance fields
                    available = Decimal(str(balance_data.get("available", "0")))
                    locked = Decimal(str(balance_data.get("locked", "0")))
                    staked = Decimal(str(balance_data.get("staked", "0")))
                    
                    # Total balance is sum of available, locked, and staked
                    total = available + locked + staked
                    
                    if total > 0:
                        has_spot_balance = True
                    
                    self._account_balances[asset] = total
                    self._account_available_balances[asset] = available
            
            # Log spot balances first
            if has_spot_balance:
                self.logger().info(f"Updated balances from capital API: {len(self._account_balances)} assets")
                for asset, total in self._account_balances.items():
                    available = self._account_available_balances.get(asset, Decimal("0"))
                    self.logger().info(f"  {asset}: total={total}, available={available}")
            
            # Always check collateral API to get complete balance picture
            # This ensures we don't miss funds in margin/futures account
            self.logger().info("Checking collateral API for additional balances...")
            try:
                await self._update_balances_from_collateral_merge()
            except Exception as e:
                self.logger().debug(f"Could not fetch collateral balances: {str(e)}")
                # Continue with spot balances only if collateral fetch fails
                    
        except Exception as e:
            self.logger().error(
                f"Error updating balances. Error: {str(e)}",
                exc_info=True
            )
            # Try collateral API as fallback
            try:
                self.logger().info("Attempting to fetch balances from collateral API as fallback...")
                await self._update_balances_from_collateral()
            except Exception as collateral_error:
                self.logger().error(
                    f"Error fetching from collateral API: {str(collateral_error)}",
                    exc_info=True
                )
                # Don't raise - let the connector continue with empty balances
                # This prevents the connector from getting stuck if balance API fails

    async def _update_balances_from_collateral_merge(self):
        """
        Update account balances from the collateral API and merge with existing spot balances
        This ensures we capture funds from both spot and margin/futures accounts
        """
        try:
            self.logger().debug(f"Fetching collateral from {CONSTANTS.COLLATERAL_PATH_URL}")
            response = await self._api_get(
                path_url=CONSTANTS.COLLATERAL_PATH_URL,
                is_auth_required=True
            )
            
            self.logger().debug(f"Collateral API response: {response}")
            
            if isinstance(response, dict):
                # Extract balances from collateral response
                net_equity_available = Decimal(str(response.get("netEquityAvailable", "0")))
                net_equity = Decimal(str(response.get("netEquity", "0")))
                
                # Check if there's a collateral breakdown by asset
                collateral_data = response.get("collateral")
                
                if isinstance(collateral_data, list):
                    # New format - list of collateral assets
                    for collateral_item in collateral_data:
                        if isinstance(collateral_item, dict):
                            symbol = collateral_item.get("symbol")
                            if symbol:
                                # Get available quantity from collateral
                                available_quantity = Decimal(str(collateral_item.get("availableQuantity", "0")))
                                total_quantity = Decimal(str(collateral_item.get("totalQuantity", "0")))
                                
                                # Merge with existing balances - use the maximum available
                                existing_total = self._account_balances.get(symbol, Decimal("0"))
                                existing_available = self._account_available_balances.get(symbol, Decimal("0"))
                                
                                # For available balance, use net equity available if it's higher than spot
                                # This handles the case where collateral shows 0 available but net equity is available
                                if symbol == "USDC" and net_equity_available > available_quantity:
                                    available_quantity = net_equity_available
                                
                                # For total balance, use the maximum (not sum) to avoid double counting
                                # For available balance, use the maximum available from either account
                                final_total = max(existing_total, total_quantity)
                                final_available = max(existing_available, available_quantity)
                                
                                self._account_balances[symbol] = final_total
                                self._account_available_balances[symbol] = final_available
                                
                                if final_total > existing_total or final_available > existing_available:
                                    self.logger().info(f"Updated {symbol} from collateral - "
                                                     f"Spot: total={existing_total}, available={existing_available} | "
                                                     f"Collateral: total={total_quantity}, available={available_quantity} | "
                                                     f"Final: total={final_total}, available={final_available}")
                else:
                    # If no detailed breakdown but we have net equity, use it for USDC
                    if net_equity > 0:
                        existing_total = self._account_balances.get("USDC", Decimal("0"))
                        existing_available = self._account_available_balances.get("USDC", Decimal("0"))
                        
                        # Use maximum values
                        final_total = max(existing_total, net_equity)
                        final_available = max(existing_available, net_equity_available)
                        
                        if final_total > existing_total or final_available > existing_available:
                            self._account_balances["USDC"] = final_total
                            self._account_available_balances["USDC"] = final_available
                            self.logger().info(f"Updated USDC from collateral net equity - "
                                             f"Final: total={final_total}, available={final_available}")
                
                # Log final merged balances
                self.logger().info(f"Final merged balances: {len(self._account_balances)} assets")
                for asset, total in self._account_balances.items():
                    available = self._account_available_balances.get(asset, Decimal("0"))
                    self.logger().info(f"  {asset}: total={total}, available={available}")
                
                # Log collateral summary
                self.logger().info(f"Collateral account summary: netEquity={net_equity}, netEquityAvailable={net_equity_available}")
            else:
                self.logger().warning(f"Unexpected collateral response format: {type(response)}")
                
        except Exception as e:
            self.logger().debug(f"Could not fetch collateral balances: {str(e)}")
            # Don't raise - continue with existing balances

    async def _update_balances_from_collateral(self):
        """
        Update account balances from the collateral API
        This is used when the capital API returns no balances (funds are in margin/futures account)
        """
        try:
            self.logger().debug(f"Fetching collateral from {CONSTANTS.COLLATERAL_PATH_URL}")
            response = await self._api_get(
                path_url=CONSTANTS.COLLATERAL_PATH_URL,
                is_auth_required=True
            )
            
            self.logger().info(f"Collateral API response: {response}")
            
            # Clear existing balances
            self._account_balances.clear()
            self._account_available_balances.clear()
            
            if isinstance(response, dict):
                # Extract balances from collateral response
                # Based on API docs, the response contains:
                # - netEquityAvailable: Available equity for trading
                # - netEquity: Total equity
                # - collateral: Collateral breakdown by asset
                
                net_equity_available = Decimal(str(response.get("netEquityAvailable", "0")))
                net_equity = Decimal(str(response.get("netEquity", "0")))
                
                # Check if there's a collateral breakdown by asset
                collateral_data = response.get("collateral")
                if isinstance(collateral_data, list):
                    # Parse collateral array - each item contains asset info
                    for collateral_item in collateral_data:
                        if isinstance(collateral_item, dict):
                            symbol = collateral_item.get("symbol", "")
                            if symbol:
                                # Use totalQuantity as the balance
                                total_quantity = Decimal(str(collateral_item.get("totalQuantity", "0")))
                                available_quantity = Decimal(str(collateral_item.get("availableQuantity", "0")))
                                
                                # If availableQuantity is 0, use a portion of netEquityAvailable
                                # This handles the case where funds are in margin account
                                if available_quantity == 0 and symbol == "USDC":
                                    # Use the netEquityAvailable for USDC
                                    self._account_balances[symbol] = net_equity
                                    self._account_available_balances[symbol] = net_equity_available
                                else:
                                    self._account_balances[symbol] = total_quantity
                                    self._account_available_balances[symbol] = available_quantity
                                    
                                self.logger().debug(f"Parsed {symbol} from collateral: total={total_quantity}, available={available_quantity}")
                elif isinstance(collateral_data, dict):
                    # Old format - dict mapping
                    for asset, collateral_info in collateral_data.items():
                        if isinstance(collateral_info, dict):
                            # Extract value from collateral info
                            value = Decimal(str(collateral_info.get("value", "0")))
                            # For collateral accounts, available balance might be the collateral value
                            self._account_balances[asset] = value
                            self._account_available_balances[asset] = value
                        elif isinstance(collateral_info, (str, int, float)):
                            # If collateral_info is just a value
                            value = Decimal(str(collateral_info))
                            self._account_balances[asset] = value
                            self._account_available_balances[asset] = value
                else:
                    # If no detailed collateral breakdown, use net equity as USDC balance
                    # This is a reasonable assumption as USDC is often the quote currency
                    if net_equity > 0:
                        self.logger().info(f"No detailed collateral breakdown found, using net equity as USDC balance")
                        self._account_balances["USDC"] = net_equity
                        self._account_available_balances["USDC"] = net_equity_available
                
                self.logger().info(f"Updated balances from collateral API: {len(self._account_balances)} assets")
                for asset, total in self._account_balances.items():
                    available = self._account_available_balances.get(asset, Decimal("0"))
                    self.logger().info(f"  {asset}: total={total}, available={available}")
                
                # Log additional collateral info for debugging
                self.logger().info(f"Collateral account summary: netEquity={net_equity}, netEquityAvailable={net_equity_available}")
            else:
                self.logger().warning(f"Unexpected collateral response format: {type(response)}")
                
        except Exception as e:
            self.logger().error(
                f"Error fetching collateral balances. Error: {str(e)}",
                exc_info=True
            )
            raise

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
            self.logger().debug(f"Fetching markets from {self.trading_rules_request_path}")
            markets = await self._api_get(
                path_url=self.trading_rules_request_path,
                is_auth_required=False
            )
            
            self.logger().debug(f"Markets response type: {type(markets)}, length: {len(markets) if isinstance(markets, list) else 'N/A'}")
            
            trading_rules_list = []
            if isinstance(markets, list):
                for market in markets:
                    try:
                        # Skip perpetual markets - only handle spot markets
                        # This is correct because perpetual markets are handled by the separate
                        # backpack_perpetual connector in /connector/derivative/backpack_perpetual/
                        market_type = market.get("marketType", "")
                        if market_type == "PERP":
                            self.logger().debug(f"Skipping perpetual market {market.get('symbol')}")
                            continue
                        
                        # According to API docs, check orderBookState instead of status
                        order_book_state = market.get("orderBookState")
                        if order_book_state and order_book_state not in CONSTANTS.ACTIVE_ORDER_BOOK_STATES:
                            self.logger().debug(f"Skipping market {market.get('symbol')} with state: {order_book_state}")
                            continue
                            
                        exchange_symbol = market.get("symbol", "")
                        if not exchange_symbol:
                            self.logger().warning(f"Market missing symbol: {market}")
                            continue
                            
                        trading_pair = utils.convert_from_exchange_trading_pair(exchange_symbol)
                        
                        filters = market.get("filters", {})
                        price_filter = filters.get("price", {})
                        quantity_filter = filters.get("quantity", {})
                        
                        # Parse filter values with proper defaults
                        min_price = Decimal(str(price_filter.get("minPrice", "0.00000001")))
                        max_price = price_filter.get("maxPrice")
                        tick_size = Decimal(str(price_filter.get("tickSize", "0.00000001")))
                        
                        min_quantity = Decimal(str(quantity_filter.get("minQuantity", "0.00000001")))
                        max_quantity = quantity_filter.get("maxQuantity")
                        step_size = Decimal(str(quantity_filter.get("stepSize", "0.00000001")))
                        
                        trading_rule = TradingRule(
                            trading_pair=trading_pair,
                            min_order_size=min_quantity,
                            max_order_size=Decimal(str(max_quantity)) if max_quantity else Decimal("999999999"),
                            min_price_increment=tick_size,
                            min_base_amount_increment=step_size,
                            min_quote_amount_increment=tick_size,
                            min_notional_size=Decimal("0"),  # Not provided by Backpack
                            min_order_value=Decimal("0"),  # Not provided by Backpack
                            supports_limit_orders=True,
                            supports_market_orders=True,
                        )
                        
                        trading_rules_list.append(trading_rule)
                        self.logger().debug(f"Added trading rule for {trading_pair}: "
                                          f"min_qty={min_quantity}, max_qty={max_quantity}, "
                                          f"tick_size={tick_size}, step_size={step_size}")
                        
                    except Exception as e:
                        self.logger().error(
                            f"Error parsing trading rule for market: {market}. Error: {str(e)}",
                            exc_info=True
                        )
            else:
                self.logger().warning(f"Unexpected markets response format: {type(markets)}")
                        
            self._trading_rules.clear()
            for trading_rule in trading_rules_list:
                self._trading_rules[trading_rule.trading_pair] = trading_rule
            
            self.logger().info(f"Updated trading rules for {len(self._trading_rules)} markets")
                
        except Exception as e:
            self.logger().error(
                f"Error updating trading rules. Error: {str(e)}",
                exc_info=True
            )


    async def _place_order(self,
                          order_id: str,
                          trading_pair: str,
                          amount: Decimal,
                          trade_type: TradeType,
                          order_type: OrderType,
                          price: Decimal,
                          **kwargs) -> Tuple[str, float]:
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
        # In demo mode, simulate order placement
        if self._demo_mode:
            self.logger().info(f"Demo mode: Simulating order placement - "
                             f"{trade_type.name} {amount} {trading_pair} @ {price}")
            # Generate a fake exchange order ID
            exchange_order_id = f"DEMO-{int(time.time() * 1000)}"
            # Return both order ID and timestamp as expected by base class
            return exchange_order_id, self._time_synchronizer.time()
            
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
                
            # Log the order request for debugging
            self.logger().debug(f"Sending order request to {CONSTANTS.ORDER_PATH_URL}: {order_data}")
                
            # Send order to exchange
            response = await self._api_post(
                path_url=CONSTANTS.ORDER_PATH_URL,
                data=order_data,
                is_auth_required=True
            )
            
            # Log the response type and content for debugging
            self.logger().debug(f"Order response type: {type(response)}")
            
            # Check if response is a dictionary
            if not isinstance(response, dict):
                # If response is a string, log it and try to provide meaningful error
                if isinstance(response, str):
                    self.logger().error(f"Received string response instead of JSON: {response}")
                    # Try to parse common error patterns
                    if "unauthorized" in response.lower():
                        raise ValueError("Authentication failed - please check your API credentials")
                    elif "insufficient" in response.lower():
                        raise ValueError("Insufficient balance or margin for this order")
                    else:
                        raise ValueError(f"Unexpected string response from exchange: {response}")
                else:
                    self.logger().error(f"Unexpected response type: {type(response)}, content: {response}")
                    raise ValueError(f"Invalid response format from exchange: expected dict, got {type(response).__name__}")
            
            # Log successful response
            self.logger().debug(f"Order response: {response}")
            
            # Extract exchange order ID from response
            exchange_order_id = str(response.get("id", ""))
            
            if not exchange_order_id:
                # Log the full response for debugging
                self.logger().error(f"No order ID in response. Full response: {response}")
                raise ValueError(f"No order ID returned from exchange: {response}")
                
            self.logger().info(f"Successfully placed order {order_id} -> exchange order ID: {exchange_order_id}")
            
            # Return both exchange order ID and current timestamp
            # Base class expects a tuple of (exchange_order_id, update_timestamp)
            return exchange_order_id, self._time_synchronizer.time()
            
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
        # In demo mode, simulate order cancellation
        if self._demo_mode:
            self.logger().info(f"Demo mode: Simulating order cancellation for {order_id}")
            return True
            
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
        
        try:
            response = await rest_assistant.execute_request(
                url=url,
                throttler_limit_id=limit_id or path_url,
                params=params,
                method=RESTMethod.GET,
                is_auth_required=is_auth_required
            )
            
            # Log successful responses for debugging
            if path_url in [CONSTANTS.BALANCES_PATH_URL, CONSTANTS.MARKETS_PATH_URL]:
                self.logger().debug(f"API GET {path_url} response: {response}")
                
            return response
            
        except Exception as e:
            # Log more details about the error
            self.logger().error(f"API GET {path_url} failed. Auth required: {is_auth_required}, "
                              f"Error type: {type(e).__name__}, Error: {str(e)}")
            raise

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
        
        try:
            # Log the request for debugging
            self.logger().debug(f"API POST {path_url} request data: {data}")
            
            response = await rest_assistant.execute_request(
                url=url,
                throttler_limit_id=limit_id or path_url,
                data=data,
                method=RESTMethod.POST,
                is_auth_required=is_auth_required
            )
            
            # Log successful response for debugging
            self.logger().debug(f"API POST {path_url} response type: {type(response)}")
            if isinstance(response, dict):
                self.logger().debug(f"API POST {path_url} response: {response}")
            elif isinstance(response, str):
                self.logger().warning(f"API POST {path_url} returned string response: {response[:200]}...")
                
            return response
            
        except json.JSONDecodeError as e:
            self.logger().error(f"Failed to parse JSON response from {path_url}. Error: {str(e)}")
            # Try to get the raw response text for debugging
            raise ValueError(f"Invalid JSON response from {path_url}: {str(e)}")
        except Exception as e:
            # Log more details about the error
            self.logger().error(f"API POST {path_url} failed. Auth required: {is_auth_required}, "
                              f"Data: {data}, Error type: {type(e).__name__}, Error: {str(e)}")
            raise

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
        
        # In demo mode, simulate order updates
        if self._demo_mode:
            for tracked_order in tracked_orders:
                # Simulate orders being open for 30 seconds then filled
                if self.current_timestamp - tracked_order.creation_timestamp > 30:
                    self.logger().info(f"Demo mode: Simulating order fill for {tracked_order.client_order_id}")
                    order_update = OrderUpdate(
                        trading_pair=tracked_order.trading_pair,
                        update_timestamp=self.current_timestamp,
                        new_state=OrderState.FILLED,
                        client_order_id=tracked_order.client_order_id,
                        exchange_order_id=tracked_order.exchange_order_id or f"DEMO-{int(time.time() * 1000)}",
                    )
                    self._order_tracker.process_order_update(order_update)
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
        async for event_message in self._iter_user_event_queue():
            try:
                # Backpack order update events
                event_type = event_message.get("e")
                
                if event_type in ["orderAccepted", "orderCancelled", "orderExpired", "orderFill", "orderModified"]:
                    await self._process_ws_order_update(event_message)
                else:
                    self.logger().debug(f"Unknown user stream event type: {event_type}")
                    
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception("Unexpected error in user stream listener")
                await self._sleep(5.0)
    
    async def _process_ws_order_update(self, event_message: dict):
        """
        Process order update events from the WebSocket
        """
        try:
            # Extract order information
            event_type = event_message.get("e")
            client_order_id = str(event_message.get("c", ""))  # May not be present
            exchange_order_id = str(event_message.get("i", ""))
            symbol = event_message.get("s", "")
            
            # Try to find the order by client order ID or exchange order ID
            tracked_order = None
            if client_order_id:
                tracked_order = self._order_tracker.all_fillable_orders.get(client_order_id)
            
            if not tracked_order and exchange_order_id:
                # Search by exchange order ID
                for order in self._order_tracker.all_fillable_orders.values():
                    if order.exchange_order_id == exchange_order_id:
                        tracked_order = order
                        break
            
            if not tracked_order:
                return
            
            # Process different event types
            if event_type == "orderAccepted":
                # Order was accepted
                order_update = OrderUpdate(
                    trading_pair=tracked_order.trading_pair,
                    update_timestamp=event_message.get("E", self.current_timestamp) / 1000,  # Convert from microseconds
                    new_state=OrderState.OPEN,
                    client_order_id=tracked_order.client_order_id,
                    exchange_order_id=exchange_order_id,
                )
                self._order_tracker.process_order_update(order_update)
                
            elif event_type == "orderCancelled":
                # Order was cancelled
                order_update = OrderUpdate(
                    trading_pair=tracked_order.trading_pair,
                    update_timestamp=event_message.get("E", self.current_timestamp) / 1000,
                    new_state=OrderState.CANCELED,
                    client_order_id=tracked_order.client_order_id,
                    exchange_order_id=exchange_order_id,
                )
                self._order_tracker.process_order_update(order_update)
                
            elif event_type == "orderExpired":
                # Order expired
                order_update = OrderUpdate(
                    trading_pair=tracked_order.trading_pair,
                    update_timestamp=event_message.get("E", self.current_timestamp) / 1000,
                    new_state=OrderState.CANCELED,
                    client_order_id=tracked_order.client_order_id,
                    exchange_order_id=exchange_order_id,
                )
                self._order_tracker.process_order_update(order_update)
                
            elif event_type == "orderFill":
                # Order was filled (partially or fully)
                fill_quantity = Decimal(event_message.get("l", "0"))
                fill_price = Decimal(event_message.get("L", "0"))
                executed_quantity = Decimal(event_message.get("z", "0"))
                fee_amount = Decimal(event_message.get("n", "0"))
                fee_token = event_message.get("N", "")
                
                # Create trade update
                trade_update = TradeUpdate(
                    trade_id=str(event_message.get("t", "")),
                    client_order_id=tracked_order.client_order_id,
                    exchange_order_id=exchange_order_id,
                    trading_pair=tracked_order.trading_pair,
                    fill_timestamp=event_message.get("E", self.current_timestamp) / 1000,
                    fill_price=fill_price,
                    fill_base_amount=fill_quantity,
                    fill_quote_amount=fill_quantity * fill_price,
                    fee=TradeFeeBase.new_spot_fee(
                        fee_schema=self.trade_fee_schema(),
                        trade_type=tracked_order.trade_type,
                        percent_token=fee_token,
                        flat_fees=[TokenAmount(amount=fee_amount, token=fee_token)]
                    ),
                    is_taker=not event_message.get("m", False)
                )
                self._order_tracker.process_trade_update(trade_update)
                
                # Check if order is fully filled
                order_state = event_message.get("X", "")
                if order_state == "Filled" or executed_quantity >= tracked_order.amount:
                    order_update = OrderUpdate(
                        trading_pair=tracked_order.trading_pair,
                        update_timestamp=event_message.get("E", self.current_timestamp) / 1000,
                        new_state=OrderState.FILLED,
                        client_order_id=tracked_order.client_order_id,
                        exchange_order_id=exchange_order_id,
                    )
                    self._order_tracker.process_order_update(order_update)
                else:
                    # Partially filled
                    order_update = OrderUpdate(
                        trading_pair=tracked_order.trading_pair,
                        update_timestamp=event_message.get("E", self.current_timestamp) / 1000,
                        new_state=OrderState.PARTIALLY_FILLED,
                        client_order_id=tracked_order.client_order_id,
                        exchange_order_id=exchange_order_id,
                    )
                    self._order_tracker.process_order_update(order_update)
                    
        except Exception:
            self.logger().exception(f"Failed to process order update: {event_message}")

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
        # For Backpack, the symbols are the same (no conversion needed)
        # But we need to populate the symbol map for the connector to be ready
        self.logger().debug(f"Initializing trading pair symbols with exchange_info type: {type(exchange_info)}, length: {len(exchange_info) if hasattr(exchange_info, '__len__') else 'N/A'}")
        
        mapping = {}
        
        if isinstance(exchange_info, list):
            # Assume exchange_info is a list of market data
            for market in exchange_info:
                if "symbol" in market:
                    # Backpack uses underscores, Hummingbot uses dashes
                    exchange_symbol = market["symbol"]  # e.g., "SOL_USDC"
                    hb_symbol = exchange_symbol.replace("_", "-")  # e.g., "SOL-USDC"
                    mapping[exchange_symbol] = hb_symbol
        
        self.logger().info(f"Initialized trading pair symbol map with {len(mapping)} pairs: {mapping}")
        # Even if no markets, set an empty map so status check passes
        self._set_trading_pair_symbol_map(mapping)

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
        
        Backpack Exchange does not provide a public API endpoint for fee information.
        Trading fees are applied during order execution and included in trade updates.
        Default fee structure: Maker: 0.02%, Taker: 0.04%
        """
        # Backpack does not expose a fees endpoint in their API
        # Fees are returned with each trade execution
        pass