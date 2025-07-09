from typing import Any, Dict, Optional

import hummingbot.connector.exchange.backpack.backpack_constants as CONSTANTS
from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.connector.utils import get_new_client_order_id
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory


def public_rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """
    Creates a full URL for the public REST API

    :param path_url: The specific path for the endpoint
    :param domain: The domain to use (not used for Backpack as it has a single domain)
    :return: The full URL for the endpoint
    """
    return f"{CONSTANTS.REST_URL}{path_url}"


def private_rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """
    Creates a full URL for the private REST API

    :param path_url: The specific path for the endpoint
    :param domain: The domain to use (not used for Backpack as it has a single domain)
    :return: The full URL for the endpoint
    """
    return f"{CONSTANTS.REST_URL}{path_url}"


def wss_url(domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """
    Creates the WebSocket URL

    :param domain: The domain to use (not used for Backpack as it has a single domain)
    :return: The WebSocket URL
    """
    return CONSTANTS.WSS_URL


def build_api_factory(
    throttler: Optional[AsyncThrottler] = None,
    time_synchronizer: Optional[TimeSynchronizer] = None,
    auth: Optional[AuthBase] = None,
) -> WebAssistantsFactory:
    """
    Builds the API factory for creating web assistants

    :param throttler: The throttler to use for rate limiting
    :param time_synchronizer: The time synchronizer for time-sensitive operations
    :param auth: The authentication handler
    :return: The web assistants factory
    """
    api_factory = WebAssistantsFactory(
        throttler=throttler,
        auth=auth,
        rest_pre_processors=[],
        rest_post_processors=[],
    )
    return api_factory


def get_order_book_url(trading_pair: str) -> str:
    """
    Get the URL for order book data

    :param trading_pair: The trading pair in exchange format
    :return: The URL for the order book endpoint
    """
    return public_rest_url(CONSTANTS.DEPTH_PATH_URL)


def get_ticker_url(trading_pair: Optional[str] = None) -> str:
    """
    Get the URL for ticker data

    :param trading_pair: The trading pair in exchange format (optional)
    :return: The URL for the ticker endpoint
    """
    if trading_pair:
        return public_rest_url(CONSTANTS.TICKER_PATH_URL)
    else:
        return public_rest_url(CONSTANTS.TICKERS_PATH_URL)


def get_markets_url() -> str:
    """
    Get the URL for markets data

    :return: The URL for the markets endpoint
    """
    return public_rest_url(CONSTANTS.MARKETS_PATH_URL)


def get_trades_url(trading_pair: str) -> str:
    """
    Get the URL for recent trades

    :param trading_pair: The trading pair in exchange format
    :return: The URL for the trades endpoint
    """
    return public_rest_url(CONSTANTS.TRADES_PATH_URL)


def create_ws_subscribe_message(streams: list) -> Dict[str, Any]:
    """
    Create a WebSocket subscription message

    :param streams: List of stream names to subscribe to
    :return: The subscription message
    """
    return {
        "method": "SUBSCRIBE",
        "params": streams
    }


def create_ws_unsubscribe_message(streams: list) -> Dict[str, Any]:
    """
    Create a WebSocket unsubscription message

    :param streams: List of stream names to unsubscribe from
    :return: The unsubscription message
    """
    return {
        "method": "UNSUBSCRIBE",
        "params": streams
    }


def get_ws_stream_name(stream_type: str, trading_pair: str) -> str:
    """
    Get the WebSocket stream name for a specific trading pair

    :param stream_type: Type of stream (e.g., "depth", "ticker", "trade")
    :param trading_pair: The trading pair in exchange format
    :return: The stream name
    """
    return f"{stream_type}.{trading_pair}"


def get_kline_ws_stream_name(interval: str, trading_pair: str) -> str:
    """
    Get the WebSocket stream name for K-line data

    :param interval: K-line interval (e.g., "1m", "5m", "1h")
    :param trading_pair: The trading pair in exchange format
    :return: The K-line stream name
    """
    return f"kline.{interval}.{trading_pair}"


def is_exchange_information_valid(exchange_info: Dict[str, Any]) -> bool:
    """
    Check if the exchange information is valid

    :param exchange_info: The exchange information from the API
    :return: True if valid, False otherwise
    """
    return (
        isinstance(exchange_info, dict) 
        and "symbol" in exchange_info
        and "filters" in exchange_info
    )