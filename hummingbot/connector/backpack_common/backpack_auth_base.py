"""
Base authentication class for Backpack Exchange using ED25519 signatures

This base class provides common authentication functionality for both
spot and perpetual Backpack Exchange connectors.
"""
import base64
import json
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlencode

import nacl.encoding
import nacl.signing
from nacl.signing import SigningKey

from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest, WSRequest


class BackpackAuthBase(AuthBase, ABC):
    """
    Base authentication class for Backpack Exchange using ED25519 signatures
    
    Both spot and perpetual connectors inherit from this base class.
    """

    def __init__(self, api_key: str, api_secret: str):
        """
        Initialize Backpack authentication
        
        :param api_key: The API key (public key)
        :param api_secret: Base64 encoded ED25519 private key (signing key)
        """
        self.api_key = api_key
        # Decode the base64 encoded private key
        try:
            self.signing_key = SigningKey(base64.b64decode(api_secret))
        except Exception as e:
            raise ValueError(f"Invalid API secret format. Must be base64 encoded ED25519 private key: {str(e)}")
        
        self._logger = None
    
    @abstractmethod
    def _get_instruction_for_endpoint(self, url: str, method: Optional[str] = None) -> str:
        """
        Get the instruction string for a given endpoint
        
        This method must be implemented by subclasses as spot and perpetual
        may have different endpoint mappings.
        
        :param url: The API endpoint URL
        :param method: The HTTP method (GET, POST, DELETE)
        :return: Instruction string for authentication
        """
        pass
    
    def generate_auth_string(
        self,
        instruction: str,
        params: Optional[Union[Dict[str, Any], str]] = None,
        timestamp: int = None,
        window: int = 5000
    ) -> str:
        """
        Generate the authentication string to be signed
        
        :param instruction: The API instruction (e.g., "orderExecute")
        :param params: Request parameters (dict or JSON string)
        :param timestamp: Timestamp in milliseconds
        :param window: Time window in milliseconds
        :return: Authentication string
        """
        if timestamp is None:
            timestamp = int(time.time() * 1000)
        
        # Build the base auth components
        auth_components = [
            f"instruction={instruction}",
        ]
        
        # Handle parameters
        if params:
            if isinstance(params, str):
                # Try to parse as JSON
                try:
                    params = json.loads(params)
                except json.JSONDecodeError:
                    # If not JSON, treat as raw string
                    pass
            
            if isinstance(params, dict):
                # Sort parameters alphabetically and add to auth string
                sorted_params = sorted(params.items())
                for key, value in sorted_params:
                    auth_components.append(f"{key}={value}")
        
        # Add timestamp and window
        auth_components.append(f"timestamp={timestamp}")
        auth_components.append(f"window={window}")
        
        return "&".join(auth_components)
    
    def get_signature(self, message: str) -> str:
        """
        Sign a message using ED25519
        
        :param message: The message to sign
        :return: Base64 encoded signature
        """
        signed = self.signing_key.sign(message.encode())
        # Return only the signature part (first 64 bytes), base64 encoded
        signature = signed.signature
        return base64.b64encode(signature).decode()
    
    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        """
        Apply authentication to REST request
        
        :param request: The REST request to authenticate
        :return: Authenticated request
        """
        # Get the instruction for this endpoint
        instruction = self._get_instruction_for_endpoint(request.url, request.method.name)
        
        # Get timestamp
        timestamp = int(time.time() * 1000)
        window = 5000
        
        # Prepare parameters
        params = None
        if request.method.name in ["GET", "DELETE"]:
            params = request.params
        elif request.method.name in ["POST", "PUT"]:
            params = request.data
        
        # Generate auth string
        auth_string = self.generate_auth_string(
            instruction=instruction,
            params=params,
            timestamp=timestamp,
            window=window
        )
        
        # Sign the auth string
        signature = self.get_signature(auth_string)
        
        # Add authentication headers
        auth_headers = {
            "X-API-KEY": self.api_key,
            "X-SIGNATURE": signature,
            "X-TIMESTAMP": str(timestamp),
            "X-WINDOW": str(window),
        }
        
        if request.headers is None:
            request.headers = {}
        request.headers.update(auth_headers)
        
        return request
    
    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        """
        Apply authentication to WebSocket request
        
        For WebSocket subscriptions, authentication is included in the subscription message
        
        :param request: The WebSocket request
        :return: The request unchanged (auth handled in subscription)
        """
        # WebSocket authentication is handled in the subscription message
        return request
    
    def get_ws_auth_payload(self, streams: List[str]) -> Dict[str, Any]:
        """
        Generate WebSocket authentication payload for subscribing to private streams
        
        :param streams: List of stream names to subscribe to
        :return: Authentication payload for WebSocket subscription
        """
        # Get timestamp
        timestamp = int(time.time() * 1000)
        window = 5000
        
        # Generate auth string for WebSocket subscription
        auth_string = self.generate_auth_string(
            instruction="subscribe",
            params={"streams": ",".join(streams)},
            timestamp=timestamp,
            window=window
        )
        
        # Sign the auth string
        signature = self.get_signature(auth_string)
        
        # Return subscription payload with auth
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