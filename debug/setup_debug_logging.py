"""
Setup debug logging for Backpack Exchange testing
Load configuration from backpack_debug_config.yml
"""

import logging
import yaml
import os
from pathlib import Path


def setup_debug_logging(config_path: str = None):
    """
    Setup logging based on debug configuration
    
    :param config_path: Path to debug config file
    """
    if config_path is None:
        config_path = Path(__file__).parent / "backpack_debug_config.yml"
    
    # Load configuration
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Get logging config
    log_config = config.get('logging', {})
    
    # Set up root logger
    root_level = getattr(logging, log_config.get('level', 'INFO'))
    logging.getLogger().setLevel(root_level)
    
    # Configure specific loggers
    for logger_name, logger_config in log_config.get('loggers', {}).items():
        logger = logging.getLogger(logger_name)
        level = getattr(logging, logger_config.get('level', 'INFO'))
        logger.setLevel(level)
    
    # Set up debug file handler if specified
    debug_config = config.get('debug', {})
    if debug_config.get('save_to_file'):
        log_file = debug_config.get('log_file', 'backpack_debug.log')
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        logging.getLogger().addHandler(file_handler)
    
    return config


def get_test_config(config_path: str = None):
    """Get test configuration parameters"""
    if config_path is None:
        config_path = Path(__file__).parent / "backpack_debug_config.yml"
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    return config.get('test', {})


# HTTP Request/Response Logger
class HTTPDebugLogger:
    """Logger for HTTP requests and responses"""
    
    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger("backpack.http.debug")
        
    def log_request(self, method: str, url: str, headers: dict = None, body: any = None):
        """Log HTTP request details"""
        if not self.config.get('log_http_requests'):
            return
            
        self.logger.debug(f"HTTP Request: {method} {url}")
        
        if self.config.get('log_headers') and headers:
            # Mask sensitive headers
            safe_headers = self._mask_sensitive_headers(headers)
            self.logger.debug(f"Headers: {safe_headers}")
        
        if body:
            self.logger.debug(f"Body: {body}")
    
    def log_response(self, status: int, headers: dict = None, body: any = None):
        """Log HTTP response details"""
        if not self.config.get('log_http_requests'):
            return
            
        self.logger.debug(f"HTTP Response: {status}")
        
        if self.config.get('log_headers') and headers:
            self.logger.debug(f"Response Headers: {headers}")
        
        if self.config.get('log_response_body') and body:
            self.logger.debug(f"Response Body: {body}")
    
    def _mask_sensitive_headers(self, headers: dict) -> dict:
        """Mask sensitive header values"""
        sensitive_keys = ['X-API-Key', 'X-Signature', 'Authorization']
        safe_headers = headers.copy()
        
        for key in sensitive_keys:
            if key in safe_headers:
                # Show first and last 4 characters only
                value = safe_headers[key]
                if len(value) > 8:
                    safe_headers[key] = f"{value[:4]}...{value[-4:]}"
                else:
                    safe_headers[key] = "***"
        
        return safe_headers


# Signature Debug Logger
class SignatureDebugLogger:
    """Logger for ED25519 signature debugging"""
    
    def __init__(self, config: dict):
        self.config = config.get('signature', {})
        self.logger = logging.getLogger("backpack.signature.debug")
    
    def log_signing_process(self, instruction: str, params: dict, timestamp: int, window: int):
        """Log the signature generation process"""
        if not self.config.get('log_generation'):
            return
        
        self.logger.debug(f"Signing process started")
        self.logger.debug(f"Instruction: {instruction}")
        self.logger.debug(f"Parameters: {params}")
        self.logger.debug(f"Timestamp: {timestamp}")
        self.logger.debug(f"Window: {window}")
    
    def log_message_to_sign(self, message: str):
        """Log the message being signed"""
        if not self.config.get('log_message'):
            return
        
        self.logger.debug(f"Message to sign: {message}")
    
    def log_signature(self, signature: str):
        """Log the generated signature"""
        if not self.config.get('log_signature'):
            return
        
        # Mask most of the signature for security
        masked = f"{signature[:8]}...{signature[-8:]}" if len(signature) > 16 else "***"
        self.logger.debug(f"Generated signature: {masked}")


if __name__ == "__main__":
    # Example usage
    config = setup_debug_logging()
    print("Debug logging configured")
    print(f"Test config: {get_test_config()}")