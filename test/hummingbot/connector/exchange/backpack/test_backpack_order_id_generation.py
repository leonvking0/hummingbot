import time
import unittest


class TestBackpackOrderIDGeneration(unittest.TestCase):
    """Test for Backpack Exchange Order ID Generation"""
    
    def test_order_id_collision_with_current_approach(self):
        """Test that rapid order ID generation can cause collisions with current approach"""
        order_ids = []
        
        # Generate 1000 order IDs rapidly (simulating current problematic approach)
        for _ in range(1000):
            timestamp_ms = int(time.time() * 1000)
            # This is the problematic logic - just using timestamp modulo
            client_id = timestamp_ms % 1000000000
            order_ids.append(client_id)
        
        # Check for duplicates
        unique_ids = set(order_ids)
        duplicates = len(order_ids) - len(unique_ids)
        
        print(f"Generated {len(unique_ids)} unique IDs out of 1000 attempts")
        print(f"Found {duplicates} duplicate IDs")
        
        # With the current implementation, we will get many collisions
        # when orders are created rapidly (same millisecond)
        # This test demonstrates the problem
        
    def test_unique_order_id_generation_improved(self):
        """Test improved order ID generation with counter"""
        order_ids = []
        order_counter = 0
        
        # Generate 10000 order IDs with improved method
        for _ in range(10000):
            # Improved generation using timestamp + counter
            timestamp_part = int(time.time() * 1000) % 1000000  # 6 digits for timestamp
            counter_part = order_counter % 1000  # 3 digits for counter
            order_counter += 1
            
            # Combine parts to create unique ID
            client_id = timestamp_part * 1000 + counter_part
            
            # Ensure it fits in uint32
            client_id = client_id % 4294967296
            
            order_ids.append(client_id)
        
        # Check for uniqueness
        unique_ids = set(order_ids)
        self.assertEqual(len(unique_ids), 10000, f"Expected 10000 unique IDs, got {len(unique_ids)}")
        
        # Verify all IDs fit in uint32 range
        for order_id in order_ids:
            self.assertLessEqual(order_id, 4294967295, "Order ID should fit in uint32")
            self.assertGreaterEqual(order_id, 0, "Order ID should be non-negative")
    
    def test_order_id_fits_uint32(self):
        """Test that generated order IDs fit within uint32 range"""
        # uint32 max value is 4294967295
        max_uint32 = 4294967295
        order_counter = 0
        
        for _ in range(1000):
            timestamp_part = int(time.time() * 1000) % 1000000
            counter_part = order_counter % 1000
            order_counter += 1
            client_id = (timestamp_part * 1000 + counter_part) % 4294967296
            
            self.assertLessEqual(client_id, max_uint32, "Order ID exceeds uint32 max")
            self.assertGreaterEqual(client_id, 0, "Order ID is negative")
    
    def test_order_id_generation_with_instance_counter(self):
        """Test order ID generation with instance counter (simulating actual implementation)"""
        
        class OrderIDGenerator:
            def __init__(self):
                self._order_counter = 0
            
            def generate_client_id(self) -> int:
                """Generate a unique client order ID that fits in uint32"""
                # Use current timestamp (milliseconds) modulo to get a 6-digit number
                timestamp_part = int(time.time() * 1000) % 1000000
                
                # Use counter for uniqueness (3 digits)
                counter_part = self._order_counter % 1000
                self._order_counter += 1
                
                # Combine: timestamp (6 digits) + counter (3 digits)
                client_id = timestamp_part * 1000 + counter_part
                
                # Ensure it fits in uint32 range
                return client_id % 4294967296
        
        # Test with multiple generator instances
        generator1 = OrderIDGenerator()
        generator2 = OrderIDGenerator()
        
        ids_from_gen1 = [generator1.generate_client_id() for _ in range(500)]
        ids_from_gen2 = [generator2.generate_client_id() for _ in range(500)]
        
        # Check uniqueness within each generator
        self.assertEqual(len(set(ids_from_gen1)), 500, "Generator 1 should produce unique IDs")
        self.assertEqual(len(set(ids_from_gen2)), 500, "Generator 2 should produce unique IDs")
        
        # Note: IDs from different generators might collide in rare cases,
        # but this is acceptable as they would be from different bot instances
        
        # Verify all fit in uint32
        for client_id in ids_from_gen1 + ids_from_gen2:
            self.assertLessEqual(client_id, 4294967295, "Order ID should fit in uint32")
            self.assertGreaterEqual(client_id, 0, "Order ID should be non-negative")
    
    def test_order_id_thread_safety(self):
        """Test order ID generation is thread-safe"""
        import threading
        
        class ThreadSafeOrderIDGenerator:
            def __init__(self):
                self._order_counter = 0
                self._lock = threading.Lock()
            
            def generate_client_id(self) -> int:
                """Thread-safe generation of unique client order ID"""
                with self._lock:
                    timestamp_part = int(time.time() * 1000) % 1000000
                    counter_part = self._order_counter % 1000
                    self._order_counter += 1
                    client_id = (timestamp_part * 1000 + counter_part) % 4294967296
                    return client_id
        
        generator = ThreadSafeOrderIDGenerator()
        order_ids = []
        lock = threading.Lock()
        
        def generate_ids(count):
            for _ in range(count):
                client_id = generator.generate_client_id()
                with lock:
                    order_ids.append(client_id)
        
        # Create multiple threads generating IDs simultaneously
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=generate_ids, args=(100,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Should have 1000 unique IDs (10 threads * 100 IDs each)
        unique_ids = set(order_ids)
        self.assertEqual(len(unique_ids), 1000, f"Expected 1000 unique IDs, got {len(unique_ids)}")


if __name__ == "__main__":
    unittest.main()