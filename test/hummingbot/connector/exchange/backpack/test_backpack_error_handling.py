import unittest
from unittest.mock import MagicMock, patch

from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS


class TestBackpackErrorHandling(unittest.TestCase):
    """Test error response handling for Backpack Exchange"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.exchange = BackpackExchange(
            client_config_map=MagicMock(),
            api_key="test_key",
            api_secret="test_secret",
            trading_pairs=["SOL-USDC"],
            demo_mode=True
        )
    
    def test_parse_error_response_with_known_code(self):
        """Test parsing error response with known error code"""
        # Test with INSUFFICIENT_FUNDS error
        error_response = {
            "code": "INSUFFICIENT_FUNDS",
            "message": "Account has insufficient funds"
        }
        
        result = self.exchange._parse_error_response(error_response)
        
        # Should return our mapped message
        self.assertIn("Insufficient funds for this operation", result)
        self.assertIn("Code: INSUFFICIENT_FUNDS", result)
    
    def test_parse_error_response_with_unknown_code(self):
        """Test parsing error response with unknown error code"""
        error_response = {
            "code": "UNKNOWN_ERROR_CODE",
            "message": "Some unknown error occurred"
        }
        
        result = self.exchange._parse_error_response(error_response)
        
        # Should fall back to API message
        self.assertIn("Some unknown error occurred", result)
        self.assertIn("Code: UNKNOWN_ERROR_CODE", result)
    
    def test_parse_error_response_without_code(self):
        """Test parsing response without error code"""
        error_response = {
            "some_field": "some_value"
        }
        
        result = self.exchange._parse_error_response(error_response)
        
        # Should return generic message
        self.assertIn("Unknown error response", result)
    
    def test_is_order_not_found_during_cancelation_with_code(self):
        """Test order not found detection with error code"""
        # Test with INVALID_ORDER code
        exception = ValueError("Order cancellation failed (Code: INVALID_ORDER)")
        self.assertTrue(self.exchange._is_order_not_found_during_cancelation_error(exception))
        
        # Test with RESOURCE_NOT_FOUND code
        exception = ValueError("Resource not found (Code: RESOURCE_NOT_FOUND)")
        self.assertTrue(self.exchange._is_order_not_found_during_cancelation_error(exception))
        
        # Test with different error code
        exception = ValueError("Insufficient funds (Code: INSUFFICIENT_FUNDS)")
        self.assertFalse(self.exchange._is_order_not_found_during_cancelation_error(exception))
    
    def test_is_order_not_found_during_cancelation_with_message(self):
        """Test order not found detection with error message"""
        # Test with common error phrases
        test_cases = [
            ("Order not found", True),
            ("ORDER DOES NOT EXIST", True),
            ("No such order", True),
            ("Unknown order ID", True),
            ("Insufficient balance", False),
            ("Network error", False),
        ]
        
        for error_msg, expected in test_cases:
            exception = ValueError(error_msg)
            result = self.exchange._is_order_not_found_during_cancelation_error(exception)
            self.assertEqual(result, expected, f"Failed for message: {error_msg}")
    
    def test_is_order_not_found_during_status_update(self):
        """Test order not found detection during status update"""
        # Test with INVALID_ORDER code
        exception = ValueError("Order status update failed (Code: INVALID_ORDER)")
        self.assertTrue(self.exchange._is_order_not_found_during_status_update_error(exception))
        
        # Test with common error phrase
        exception = ValueError("Order does not exist")
        self.assertTrue(self.exchange._is_order_not_found_during_status_update_error(exception))
        
        # Test with unrelated error
        exception = ValueError("Connection timeout")
        self.assertFalse(self.exchange._is_order_not_found_during_status_update_error(exception))
    
    def test_all_error_codes_have_messages(self):
        """Test that all error codes have corresponding messages"""
        # Check that all enum values have messages
        for error_code in CONSTANTS.BackpackErrorCode:
            self.assertIn(
                error_code, 
                CONSTANTS.ERROR_CODE_MESSAGES,
                f"Missing message for error code: {error_code.value}"
            )
            
            # Check message is not empty
            message = CONSTANTS.ERROR_CODE_MESSAGES[error_code]
            self.assertTrue(message, f"Empty message for error code: {error_code.value}")
    
    def test_order_not_found_errors_constant(self):
        """Test ORDER_NOT_FOUND_ERRORS constant contains correct codes"""
        expected_codes = {
            CONSTANTS.BackpackErrorCode.INVALID_ORDER,
            CONSTANTS.BackpackErrorCode.RESOURCE_NOT_FOUND,
        }
        
        self.assertEqual(CONSTANTS.ORDER_NOT_FOUND_ERRORS, expected_codes)


if __name__ == "__main__":
    unittest.main()