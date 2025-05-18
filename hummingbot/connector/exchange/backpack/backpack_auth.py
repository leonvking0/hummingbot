"""Authentication utilities for Backpack exchange."""

import base64
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest, WSRequest, RESTMethod


class BackpackAuth(AuthBase):
    """Authentication helper for Backpack exchange."""

    def __init__(self, api_key: str, secret_key: str, time_provider: TimeSynchronizer):
        self.api_key = api_key
        self._private_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(secret_key))
        self.time_provider = time_provider

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        """Add authentication headers to REST requests."""
        timestamp = str(int(self.time_provider.time() * 1000))
        window = "5000"
        signature = self._generate_signature(timestamp, window, request.method, request.url, request.data or request.params)
        headers = request.headers or {}
        headers.update({
            "X-API-Key": self.api_key,
            "X-Timestamp": timestamp,
            "X-Window": window,
            "X-Signature": signature,
        })
        request.headers = headers
        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        """Configure WebSocket auth payload."""
        timestamp = str(int(self.time_provider.time() * 1000))
        window = "5000"
        sign_str = self._build_signing_string("subscribe", timestamp, window, None)
        signature = base64.b64encode(self._private_key.sign(sign_str.encode())).decode()
        request.payload.update({"signature": [self.api_key, signature, timestamp, window]})
        return request

    def _generate_signature(
        self,
        timestamp: str,
        window: str,
        method: RESTMethod,
        url: str,
        params: Optional[Dict[str, Any]],
    ) -> str:
        sign_str = self._build_signing_string(method, timestamp, window, params, url)
        signature = self._private_key.sign(sign_str.encode())
        return base64.b64encode(signature).decode()

    def _build_signing_string(
        self,
        method: RESTMethod | str,
        timestamp: str,
        window: str,
        params: Optional[Dict[str, Any]],
        url: Optional[str] = None,
    ) -> str:
        if params is None:
            param_str = ""
        elif isinstance(params, dict):
            param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        else:
            param_str = str(params)

        if url is not None:
            instruction = self._instruction_for_request(method, url)
        else:
            instruction = method  # method holds instruction when url is None

        signing_parts = [f"instruction={instruction}"]
        if param_str:
            signing_parts.append(param_str)
        signing_parts.append(f"timestamp={timestamp}")
        signing_parts.append(f"window={window}")
        return "&".join(signing_parts)

    def _instruction_for_request(self, method: RESTMethod, url: str) -> str:
        path = url.replace(CONSTANTS.REST_URL, "")
        path = path.split("?")[0]
        if path.startswith(CONSTANTS.ORDERS_PATH_URL):
            if method == RESTMethod.POST:
                return "orderExecute"
            if method == RESTMethod.DELETE:
                return "orderCancel"
            if method == RESTMethod.GET:
                if path == CONSTANTS.ORDERS_PATH_URL:
                    return "orderQueryAll"
                else:
                    return "orderQuery"
        if path == CONSTANTS.BALANCE_PATH_URL:
            return "balanceQuery"
        return "accountQuery"
