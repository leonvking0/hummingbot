"""Authentication utilities for Backpack exchange."""

import hmac
import hashlib
from typing import Any, Dict, Optional

from hummingbot.connector.exchange.backpack_exchange import backpack_constants as CONSTANTS
from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest, WSRequest, RESTMethod


class BackpackAuth(AuthBase):
    """Authentication helper for Backpack exchange."""

    def __init__(self, api_key: str, secret_key: str, time_provider: TimeSynchronizer):
        self.api_key = api_key
        self.secret_key = secret_key
        self.time_provider = time_provider

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        """Add authentication headers to REST requests."""
        timestamp = str(int(self.time_provider.time() * 1000))
        nonce = timestamp
        signature = self._generate_signature(timestamp, nonce, request.method, request.url, request.data or request.params)
        headers = request.headers or {}
        headers.update({
            "X-BP-APIKEY": self.api_key,
            "X-BP-TIMESTAMP": timestamp,
            "X-BP-NONCE": nonce,
            "X-BP-SIGNATURE": signature,
        })
        request.headers = headers
        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        """Configure WebSocket auth payload."""
        timestamp = str(int(self.time_provider.time() * 1000))
        nonce = timestamp
        signature = self._generate_signature(timestamp, nonce, RESTMethod.GET, "/ws/auth", None)
        request.payload = {
            "op": "login",
            "args": [self.api_key, timestamp, nonce, signature],
        }
        return request

    def _generate_signature(self, timestamp: str, nonce: str, method: RESTMethod, url: str, params: Optional[Dict[str, Any]]) -> str:
        if params is None:
            payload = ""
        elif isinstance(params, dict):
            payload = "".join(f"{k}={v}" for k, v in sorted(params.items()))
        else:
            payload = str(params)
        message = f"{timestamp}{nonce}{method.value}{url}{payload}"
        return hmac.new(self.secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()
