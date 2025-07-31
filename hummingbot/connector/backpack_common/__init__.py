"""
Common utilities and base classes for Backpack Exchange connectors

This module provides shared functionality between the spot and perpetual
connectors to reduce code duplication and maintain consistency.
"""

from hummingbot.connector.backpack_common.backpack_auth_base import BackpackAuthBase
from hummingbot.connector.backpack_common.backpack_constants_base import BackpackConstantsBase
from hummingbot.connector.backpack_common.backpack_utils_base import BackpackUtilsBase
from hummingbot.connector.backpack_common.backpack_web_utils_base import BackpackWebUtilsBase

__all__ = [
    "BackpackAuthBase",
    "BackpackConstantsBase", 
    "BackpackUtilsBase",
    "BackpackWebUtilsBase",
]