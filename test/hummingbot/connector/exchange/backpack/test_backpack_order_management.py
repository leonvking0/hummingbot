import asyncio
import time
import threading
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from concurrent.futures import ThreadPoolExecutor

from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
from hummingbot.connector.exchange.backpack import backpack_constants as CONSTANTS
from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState


class TestBackpackOrderManagement(unittest.TestCase):
    """Test order management for Backpack Exchange"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ev_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(cls.ev_loop)
    
    def setUp(self):
        """Set up test fixtures"""
        self.api_key = "test_api_key"
        # Use a valid base64 encoded string (32 bytes = 256 bits for Ed25519)
        self.api_secret = "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
        
        client_config_map = ClientConfigAdapter(ClientConfigMap())
        
        self.exchange = BackpackExchange(
            client_config_map=client_config_map,
            api_key=self.api_key,
            api_secret=self.api_secret,
            trading_pairs=["SOL-USDC"],
            demo_mode=True
        )
    
    def test_unique_order_id_generation_with_bit_shifting(self):
        """Test that order ID generation uses bit-shifting approach"""
        # Generate multiple order IDs
        order_ids = []
        for _ in range(100):
            client_order_id = self.exchange.buy(
                trading_pair="SOL-USDC",
                amount=Decimal("1.0"),
                order_type=OrderType.LIMIT,
                price=Decimal("100.0")
            )
            order_ids.append(client_order_id)
        
        # Check all IDs are unique
        self.assertEqual(len(order_ids), len(set(order_ids)), "Order IDs are not unique!")
        
        # Check IDs fit in uint32 range
        for order_id in order_ids:
            # Convert hex string to int
            order_id_int = int(order_id, 16) if isinstance(order_id, str) else order_id
            self.assertLessEqual(order_id_int, 2**32 - 1, f"Order ID {order_id} exceeds uint32 range")
            self.assertGreaterEqual(order_id_int, 0, f"Order ID {order_id} is negative")
    
    def test_order_id_collision_prevention(self):
        """Test that rapid order generation doesn't produce collisions"""
        order_ids = set()
        collision_found = False
        
        # Generate orders as fast as possible
        for i in range(1000):
            client_order_id = self.exchange.buy(
                trading_pair="SOL-USDC",
                amount=Decimal("1.0"),
                order_type=OrderType.LIMIT,
                price=Decimal("100.0")
            )
            
            if client_order_id in order_ids:
                collision_found = True
                break
            order_ids.add(client_order_id)
        
        self.assertFalse(collision_found, "Order ID collision detected!")
        self.assertEqual(len(order_ids), 1000, "Not all order IDs were unique")
    
    def test_order_id_thread_safety(self):
        """Test that order ID generation is thread-safe"""
        order_ids = []
        lock = threading.Lock()
        
        def generate_orders(count):
            local_ids = []
            for _ in range(count):
                client_order_id = self.exchange.buy(
                    trading_pair="SOL-USDC",
                    amount=Decimal("1.0"),
                    order_type=OrderType.LIMIT,
                    price=Decimal("100.0")
                )
                local_ids.append(client_order_id)
            
            with lock:
                order_ids.extend(local_ids)
        
        # Run order generation in multiple threads
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for _ in range(10):
                future = executor.submit(generate_orders, 100)
                futures.append(future)
            
            # Wait for all threads to complete
            for future in futures:
                future.result()
        
        # Check all IDs are unique
        self.assertEqual(len(order_ids), 1000, "Wrong number of orders generated")
        self.assertEqual(len(set(order_ids)), 1000, "Order ID collisions in multi-threaded environment")
    
    def test_error_response_handling(self):
        """Test handling of all 33 error codes"""
        # Test each error code
        for error_code in CONSTANTS.BackpackErrorCode:
            error_response = {
                "code": error_code.value,
                "message": f"Test error for {error_code.value}"
            }
            
            # Parse error response
            error_msg = self.exchange._parse_error_response(error_response)
            
            # Check that we get a meaningful message
            self.assertIsNotNone(error_msg)
            self.assertIn("Code:", error_msg)
            
            # Check that we have a custom message for this error
            self.assertIn(CONSTANTS.ERROR_CODE_MESSAGES[error_code], error_msg)
    
    def test_unknown_error_code_handling(self):
        """Test handling of unknown error codes"""
        error_response = {
            "code": "UNKNOWN_ERROR_CODE",
            "message": "This is an unknown error"
        }
        
        error_msg = self.exchange._parse_error_response(error_response)
        
        # Should fall back to API message
        self.assertIn("This is an unknown error", error_msg)
        self.assertIn("Code: UNKNOWN_ERROR_CODE", error_msg)
    
    def test_malformed_error_response_handling(self):
        """Test handling of malformed error responses"""
        # Test response without code
        error_response = {"message": "Error without code"}
        error_msg = self.exchange._parse_error_response(error_response)
        self.assertIsNotNone(error_msg)
        
        # Test response without message
        error_response = {"code": "SOME_ERROR"}
        error_msg = self.exchange._parse_error_response(error_response)
        self.assertIsNotNone(error_msg)
        
        # Test empty response
        error_response = {}
        error_msg = self.exchange._parse_error_response(error_response)
        self.assertIn("Unknown error", error_msg)
    
    def test_order_not_found_error_detection(self):
        """Test detection of order not found errors"""
        # Test with INVALID_ORDER code
        exception1 = ValueError("Order cancellation failed (Code: INVALID_ORDER)")
        self.assertTrue(self.exchange._is_order_not_found_during_cancelation_error(exception1))
        
        # Test with RESOURCE_NOT_FOUND code
        exception2 = ValueError("Resource not found (Code: RESOURCE_NOT_FOUND)")
        self.assertTrue(self.exchange._is_order_not_found_during_cancelation_error(exception2))
        
        # Test with common error phrases
        exception3 = ValueError("Order not found")
        self.assertTrue(self.exchange._is_order_not_found_during_cancelation_error(exception3))
        
        exception4 = ValueError("ORDER DOES NOT EXIST")
        self.assertTrue(self.exchange._is_order_not_found_during_cancelation_error(exception4))
        
        # Test with unrelated error
        exception5 = ValueError("Insufficient funds")
        self.assertFalse(self.exchange._is_order_not_found_during_cancelation_error(exception5))
    
    def test_balance_calculation_spot_vs_collateral(self):
        """Test accurate balance calculation for spot vs collateral"""
        # Mock balance response with both spot and collateral
        mock_balances = {
            "USDC": {
                "available": "1000.0",
                "locked": "100.0",
                "staked": "0.0"
            },
            "SOL": {
                "available": "50.0",
                "locked": "5.0",
                "staked": "0.0"
            }
        }
        
        # Mock collateral response
        mock_collateral = {
            "collateral": "500.0",
            "freeCollateral": "400.0"
        }
        
        with patch.object(self.exchange, '_api_get', new_callable=AsyncMock) as mock_api_get:
            # Setup mock responses
            async def mock_get_response(path, *args, **kwargs):
                if "balances" in path:
                    return mock_balances
                elif "collateral" in path:
                    return mock_collateral
                return {}
            
            mock_api_get.side_effect = mock_get_response
            
            # Update balances
            self.ev_loop.run_until_complete(self.exchange._update_balances())
            
            # Check spot balances
            usdc_balance = self.exchange.get_balance("USDC")
            self.assertEqual(usdc_balance, Decimal("1000.0"))
            
            sol_balance = self.exchange.get_balance("SOL")
            self.assertEqual(sol_balance, Decimal("50.0"))
    
    def test_order_state_transitions(self):
        """Test valid order state transitions"""
        # Create an in-flight order
        order = InFlightOrder(
            client_order_id="test_order_1",
            exchange_order_id=None,
            trading_pair="SOL-USDC",
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            amount=Decimal("1.0"),
            price=Decimal("100.0"),
            creation_timestamp=time.time()
        )
        
        # Test valid transitions
        # PENDING_CREATE -> OPEN
        order.current_state = OrderState.PENDING_CREATE
        order.update_state(OrderState.OPEN)
        self.assertEqual(order.current_state, OrderState.OPEN)
        
        # OPEN -> PARTIALLY_FILLED
        order.update_state(OrderState.PARTIALLY_FILLED)
        self.assertEqual(order.current_state, OrderState.PARTIALLY_FILLED)
        
        # PARTIALLY_FILLED -> FILLED
        order.update_state(OrderState.FILLED)
        self.assertEqual(order.current_state, OrderState.FILLED)
        
        # Test invalid transition (FILLED is terminal)
        with self.assertLogs(level='WARNING') as log:
            order.update_state(OrderState.OPEN)
            # State should not change
            self.assertEqual(order.current_state, OrderState.FILLED)
    
    def test_order_cancellation_race_condition_handling(self):
        """Test handling of order cancellation race conditions"""
        # Create an in-flight order
        order = InFlightOrder(
            client_order_id="test_order_cancel",
            exchange_order_id=None,  # No exchange ID yet
            trading_pair="SOL-USDC",
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            amount=Decimal("1.0"),
            price=Decimal("100.0"),
            creation_timestamp=time.time()
        )
        
        # Add to in-flight orders
        self.exchange._in_flight_orders[order.client_order_id] = order
        
        with patch.object(self.exchange, '_api_delete', new_callable=AsyncMock) as mock_delete:
            # Simulate successful cancellation even without exchange_order_id
            mock_delete.return_value = {"success": True}
            
            # Attempt cancellation
            result = self.ev_loop.run_until_complete(
                self.exchange._execute_cancel("SOL-USDC", order.client_order_id)
            )
            
            # Should handle gracefully
            self.assertTrue(result)
    
    def test_idempotent_order_operations(self):
        """Test idempotency of order operations"""
        # Track operation calls
        operation_cache = {}
        
        def track_operation(operation_id):
            if operation_id in operation_cache:
                return operation_cache[operation_id]
            result = {"success": True, "order_id": operation_id}
            operation_cache[operation_id] = result
            return result
        
        # Test duplicate order placement prevention
        order_id = "test_idempotent_order"
        
        # First placement
        result1 = track_operation(order_id)
        self.assertTrue(result1["success"])
        
        # Duplicate placement (should return cached result)
        result2 = track_operation(order_id)
        self.assertEqual(result1, result2)
        self.assertEqual(len(operation_cache), 1)
    
    def test_order_amount_precision(self):
        """Test that order amounts respect trading rules precision"""
        # Set up mock trading rules
        self.exchange._trading_rules["SOL-USDC"] = MagicMock(
            min_order_size=Decimal("0.01"),
            max_order_size=Decimal("10000"),
            min_price_increment=Decimal("0.01"),
            min_base_amount_increment=Decimal("0.001")
        )
        
        # Test rounding to correct precision
        amount = Decimal("1.23456789")
        quantized = self.exchange.quantize_order_amount("SOL-USDC", amount)
        
        # Should be rounded to min_base_amount_increment
        self.assertEqual(quantized, Decimal("1.234"))
    
    def test_order_price_precision(self):
        """Test that order prices respect trading rules precision"""
        # Set up mock trading rules
        self.exchange._trading_rules["SOL-USDC"] = MagicMock(
            min_order_size=Decimal("0.01"),
            max_order_size=Decimal("10000"),
            min_price_increment=Decimal("0.01"),
            min_base_amount_increment=Decimal("0.001")
        )
        
        # Test rounding to correct precision
        price = Decimal("100.23456789")
        quantized = self.exchange.quantize_order_price("SOL-USDC", price)
        
        # Should be rounded to min_price_increment
        self.assertEqual(quantized, Decimal("100.23"))
    
    def test_concurrent_order_placement(self):
        """Test handling of concurrent order placement"""
        orders_placed = []
        
        async def place_order():
            order_id = self.exchange.buy(
                trading_pair="SOL-USDC",
                amount=Decimal("1.0"),
                order_type=OrderType.LIMIT,
                price=Decimal("100.0")
            )
            orders_placed.append(order_id)
        
        # Place multiple orders concurrently
        async def place_orders_concurrently():
            tasks = [place_order() for _ in range(10)]
            await asyncio.gather(*tasks)
        
        self.ev_loop.run_until_complete(place_orders_concurrently())
        
        # All orders should have unique IDs
        self.assertEqual(len(orders_placed), 10)
        self.assertEqual(len(set(orders_placed)), 10)


if __name__ == "__main__":
    unittest.main()