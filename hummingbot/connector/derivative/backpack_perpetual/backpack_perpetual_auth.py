import base64
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import nacl.encoding
import nacl.signing
from nacl.signing import SigningKey, VerifyKey

from hummingbot.connector.derivative.backpack_perpetual import backpack_perpetual_constants as CONSTANTS
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest, WSRequest


class BackpackPerpetualAuth(AuthBase):
    """
    Authentication class for Backpack Perpetual Exchange using ED25519 signatures
    """

    def __init__(self, api_key: str, api_secret: str):
        """
        Initialize Backpack Perpetual authentication

        :param api_key: Base64 encoded ED25519 public key (verifying key)
        :param api_secret: Base64 encoded ED25519 private key (signing key)
        """
        self.api_key = api_key
        # Decode the base64 encoded private key
        self._signing_key = SigningKey(base64.b64decode(api_secret))
        
    @property
    def signing_key(self) -> SigningKey:
        """Get the ED25519 signing key"""
        return self._signing_key

    def get_signature(self, message: str) -> str:
        """
        Generate ED25519 signature for the given message

        :param message: Message to sign
        :return: Base64 encoded signature
        """
        signed = self._signing_key.sign(message.encode('utf-8'))
        # Return only the signature part (excluding the message)
        return base64.b64encode(signed.signature).decode('utf-8')

    def generate_auth_string(
        self,
        instruction: str,
        params: Optional[Dict[str, Any]] = None,
        timestamp: Optional[int] = None,
        window: int = CONSTANTS.DEFAULT_REQUEST_WINDOW
    ) -> str:
        """
        Generate the authentication string for signing

        :param instruction: API instruction type
        :param params: Request parameters
        :param timestamp: Unix timestamp in milliseconds
        :param window: Request validity window in milliseconds
        :return: String to be signed
        """
        if timestamp is None:
            timestamp = int(time.time() * 1000)

        # Start with instruction
        auth_parts = [f"instruction={instruction}"]

        # Add sorted parameters if provided
        if params:
            # Sort parameters alphabetically by key
            sorted_params = sorted(params.items())
            param_string = urlencode(sorted_params)
            if param_string:
                auth_parts.append(param_string)

        # Add timestamp and window
        auth_parts.append(f"timestamp={timestamp}")
        auth_parts.append(f"window={window}")

        return "&".join(auth_parts)

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        """
        Apply authentication to REST request

        :param request: REST request to authenticate
        :return: Authenticated request
        """
        timestamp = int(time.time() * 1000)
        window = CONSTANTS.DEFAULT_REQUEST_WINDOW

        # Determine instruction based on endpoint
        instruction = self._get_instruction_for_endpoint(request.url)

        # Get parameters from either body or query
        params = None
        if request.data:
            params = request.data
        elif request.params:
            params = request.params

        # Generate auth string and signature
        auth_string = self.generate_auth_string(
            instruction=instruction,
            params=params,
            timestamp=timestamp,
            window=window
        )
        signature = self.get_signature(auth_string)

        # Add authentication headers
        headers = {
            CONSTANTS.HEADER_API_KEY: self.api_key,
            CONSTANTS.HEADER_SIGNATURE: signature,
            CONSTANTS.HEADER_TIMESTAMP: str(timestamp),
            CONSTANTS.HEADER_WINDOW: str(window),
        }

        if request.headers is None:
            request.headers = {}
        request.headers.update(headers)

        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        """
        Apply authentication to WebSocket request

        For WebSocket subscriptions, authentication is included in the subscription message
        """
        # WebSocket authentication is handled in the subscription message
        # No modification needed to the initial connection request
        return request

    def get_ws_auth_payload(self, streams: list) -> Dict[str, Any]:
        """
        Generate WebSocket authentication payload for subscribing to private streams

        :param streams: List of streams to subscribe to
        :return: Authentication payload
        """
        timestamp = int(time.time() * 1000)
        window = CONSTANTS.DEFAULT_REQUEST_WINDOW

        # Generate auth string for WebSocket subscription
        auth_string = self.generate_auth_string(
            instruction="subscribe",
            timestamp=timestamp,
            window=window
        )
        signature = self.get_signature(auth_string)

        return {
            "method": "SUBSCRIBE",
            "params": streams,
            "signature": [
                self.api_key,
                signature,
                str(timestamp),
                str(window)
            ]
        }

    def _get_instruction_for_endpoint(self, url: str) -> str:
        """
        Determine the instruction type based on the API endpoint

        :param url: API endpoint URL
        :return: Instruction type
        """
        # Map endpoints to instructions for perpetual-specific endpoints
        instruction_map = {
            "/account": "accountQuery",
            "/capital": "balanceQuery",
            "/order": "orderQuery",
            "/orders": "orderQueryAll",
            "/fills": "fillHistoryQueryAll",
            "/deposits": "depositQueryAll",
            "/withdrawals": "withdrawalQueryAll",
            "/positions": "positionQuery",
            "/history/funding": "fundingHistoryQueryAll",
            "/history/pnl": "pnlHistoryQueryAll",
            # Order execution endpoints
            "/execute": "orderExecute",
            "/cancel": "orderCancel",
            "/cancelAll": "orderCancelAll",
        }

        # Extract the path from the URL
        path = url.split("?")[0]
        
        # Check for exact endpoint matches
        for endpoint, instruction in instruction_map.items():
            if endpoint in path:
                # Special handling for order operations
                if "/order" in path:
                    if "cancel" in path.lower():
                        return "orderCancel" if "cancelAll" not in path else "orderCancelAll"
                    elif any(method in url for method in ["POST", "PUT"]):
                        # This is a heuristic; actual method should be checked differently
                        return "orderExecute"
                return instruction

        # Default instruction for unknown endpoints
        return "accountQuery"