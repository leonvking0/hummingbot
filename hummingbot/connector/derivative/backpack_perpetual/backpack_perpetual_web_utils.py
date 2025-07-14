from typing import Any, Dict, List, Optional

import hummingbot.connector.derivative.backpack_perpetual.backpack_perpetual_constants as CONSTANTS
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory


def public_rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """
    Generate public REST API URL
    """
    return f"{CONSTANTS.REST_URL}{path_url}"


def private_rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """
    Generate private REST API URL
    """
    return f"{CONSTANTS.REST_URL}{path_url}"


def wss_url(domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """
    Generate WebSocket URL
    """
    return CONSTANTS.WSS_URL


def build_api_factory(
    throttler: Optional[AsyncThrottler] = None,
    auth: Optional[Any] = None,
) -> WebAssistantsFactory:
    """
    Build API factory for making requests
    """
    throttler = throttler or AsyncThrottler(CONSTANTS.RATE_LIMITS)
    api_factory = WebAssistantsFactory(
        throttler=throttler,
        auth=auth,
    )
    return api_factory


def get_markets_url() -> str:
    """Get markets endpoint URL"""
    return public_rest_url(CONSTANTS.MARKETS_PATH_URL)


def get_ticker_url() -> str:
    """Get ticker endpoint URL"""
    return public_rest_url(CONSTANTS.TICKER_PATH_URL)


def get_order_book_url(trading_pair: str = None) -> str:
    """Get order book endpoint URL"""
    return public_rest_url(CONSTANTS.DEPTH_PATH_URL)


def get_trades_url() -> str:
    """Get trades endpoint URL"""
    return public_rest_url(CONSTANTS.TRADES_PATH_URL)


def get_funding_rate_url() -> str:
    """Get funding rate endpoint URL"""
    return public_rest_url(CONSTANTS.FUNDING_RATE_PATH_URL)


def get_funding_rates_url() -> str:
    """Get funding rates history endpoint URL"""
    return public_rest_url(CONSTANTS.FUNDING_RATES_PATH_URL)


def get_open_interest_url() -> str:
    """Get open interest endpoint URL"""
    return public_rest_url(CONSTANTS.OPEN_INTEREST_PATH_URL)


def get_account_url() -> str:
    """Get account endpoint URL"""
    return private_rest_url(CONSTANTS.ACCOUNT_PATH_URL)


def get_balances_url() -> str:
    """Get balances endpoint URL"""
    return private_rest_url(CONSTANTS.BALANCES_PATH_URL)


def get_positions_url() -> str:
    """Get positions endpoint URL"""
    return private_rest_url(CONSTANTS.POSITIONS_PATH_URL)


def get_order_url() -> str:
    """Get single order endpoint URL"""
    return private_rest_url(CONSTANTS.ORDER_PATH_URL)


def get_orders_url() -> str:
    """Get orders endpoint URL"""
    return private_rest_url(CONSTANTS.ORDERS_PATH_URL)


def get_fills_url() -> str:
    """Get fills endpoint URL"""
    return private_rest_url(CONSTANTS.FILLS_PATH_URL)


def get_funding_history_url() -> str:
    """Get funding history endpoint URL"""
    return private_rest_url(CONSTANTS.FUNDING_HISTORY_PATH_URL)


def get_pnl_history_url() -> str:
    """Get PnL history endpoint URL"""
    return private_rest_url(CONSTANTS.PNL_HISTORY_PATH_URL)


def get_ws_stream_name(stream_type: str, symbol: str = None) -> str:
    """
    Get WebSocket stream name
    Format: <type>.<symbol> or just <type> for general streams
    """
    if symbol:
        return f"{stream_type}.{symbol}"
    return stream_type


def create_ws_subscribe_message(streams: List[str], is_private: bool = False) -> Dict[str, Any]:
    """
    Create WebSocket subscription message
    
    :param streams: List of stream names to subscribe to
    :param is_private: Whether this is a private stream requiring authentication
    :return: Subscription message dict
    """
    message = {
        "method": "SUBSCRIBE",
        "params": streams
    }
    
    # Note: For private streams, signature will be added by auth handler
    return message


def create_ws_unsubscribe_message(streams: List[str]) -> Dict[str, Any]:
    """
    Create WebSocket unsubscription message
    
    :param streams: List of stream names to unsubscribe from
    :return: Unsubscription message dict
    """
    return {
        "method": "UNSUBSCRIBE",
        "params": streams
    }


def get_order_cancel_request_data(order_id: str, symbol: str) -> Dict[str, Any]:
    """
    Create order cancellation request data
    """
    return {
        "orderId": order_id,
        "symbol": symbol
    }


def get_order_placement_data(
    symbol: str,
    side: str,
    order_type: str,
    price: Optional[str] = None,
    quantity: Optional[str] = None,
    client_id: Optional[str] = None,
    time_in_force: str = CONSTANTS.DEFAULT_TIME_IN_FORCE,
    reduce_only: bool = False,
    post_only: bool = False,
) -> Dict[str, Any]:
    """
    Create order placement request data
    """
    data = {
        "symbol": symbol,
        "side": side,
        "orderType": order_type,
        "timeInForce": time_in_force,
    }
    
    if price is not None:
        data["price"] = price
    
    if quantity is not None:
        data["quantity"] = quantity
    
    if client_id is not None:
        data["clientId"] = int(client_id)
    
    if reduce_only:
        data["reduceOnly"] = reduce_only
    
    if post_only:
        data["postOnly"] = post_only
    
    return data


def get_pagination_params(limit: int = None, offset: int = None) -> Dict[str, Any]:
    """
    Get pagination parameters for API requests
    """
    params = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    return params