from decimal import Decimal
from typing import Any, Dict

from pydantic import ConfigDict, Field, SecretStr

from hummingbot.client.config.config_data_types import BaseConnectorConfigMap
from hummingbot.core.data_type.trade_fee import TradeFeeSchema

CENTRALIZED = True
EXAMPLE_PAIR = "BTC-USDT"

DEFAULT_FEES = TradeFeeSchema(
    maker_percent_fee_decimal=Decimal("0.001"),
    taker_percent_fee_decimal=Decimal("0.001"),
    buy_percent_fee_deducted_from_returns=True,
)


def is_exchange_information_valid(exchange_info: Dict[str, Any]) -> bool:
    """Validate if a trading pair is active based on exchange info."""
    status = str(exchange_info.get("status") or exchange_info.get("state") or "")
    return status.lower() in ["enabled", "trading", "active"]


class BackpackConfigMap(BaseConnectorConfigMap):
    connector: str = "backpack"
    backpack_api_key: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Backpack API key",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    backpack_secret_key: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Backpack secret key",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )

    model_config = ConfigDict(title="backpack")


KEYS = BackpackConfigMap.model_construct()
