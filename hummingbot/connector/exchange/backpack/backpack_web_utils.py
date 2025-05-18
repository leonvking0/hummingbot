from typing import Callable, Optional

from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.connector.utils import TimeSynchronizerRESTPreProcessor
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

from . import backpack_constants as CONSTANTS


def public_rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """Construct public REST URL for an endpoint."""
    return rest_url(path_url, domain)


def private_rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """Construct private REST URL for an endpoint."""
    return rest_url(path_url, domain)


def rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """Construct REST URL for an endpoint."""
    return f"{CONSTANTS.REST_URL}{path_url}"


def build_api_factory(
    throttler: Optional[AsyncThrottler] = None,
    time_synchronizer: Optional[TimeSynchronizer] = None,
    domain: str = CONSTANTS.DEFAULT_DOMAIN,
    time_provider: Optional[Callable] = None,
    auth: Optional[AuthBase] = None,
) -> WebAssistantsFactory:
    throttler = throttler or create_throttler()
    time_synchronizer = time_synchronizer or TimeSynchronizer()
    time_provider = time_provider or (lambda: get_current_server_time(throttler=throttler))
    api_factory = WebAssistantsFactory(
        throttler=throttler,
        auth=auth,
        rest_pre_processors=[
            TimeSynchronizerRESTPreProcessor(synchronizer=time_synchronizer, time_provider=time_provider)
        ],
    )
    return api_factory


def create_throttler() -> AsyncThrottler:
    return AsyncThrottler(CONSTANTS.RATE_LIMITS)


async def get_current_server_time(throttler: Optional[AsyncThrottler] = None) -> float:
    """Return the current server time from Backpack exchange."""

    throttler = throttler or create_throttler()
    api_factory = WebAssistantsFactory(throttler=throttler)
    rest_assistant = await api_factory.get_rest_assistant()
    response = await rest_assistant.execute_request_and_get_response(
        url=rest_url(CONSTANTS.SERVER_TIME_PATH_URL),
        method=RESTMethod.GET,
        throttler_limit_id=CONSTANTS.SERVER_TIME_PATH_URL,
    )

    try:
        data = await response.json()
    except Exception:
        # Some endpoints return JSON with an incorrect Content-Type header
        # noinspection PyProtectedMember
        try:
            data = await response._aiohttp_response.json(content_type=None)
        except Exception:
            text = await response.text()
            return float(text)

    server_time = float(data.get("serverTime") or data.get("time") or data.get("ts"))
    return server_time
