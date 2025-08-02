# Task: Order Management and Execution Fixes

## Related Issue
- **File**: `/Users/han/github/hummingbot/issues/order-management-issues.md`
- **Severity**: CRITICAL
- **Priority**: IMMEDIATE

## Overview
Fix critical order management issues including client order ID collisions, race conditions in cancellation, and incorrect balance calculations that could lead to failed trades and financial losses.

## Tasks Breakdown

### Task 2.1: Fix Client Order ID Generation
**Status**: [ ] Not Started
**File**: `hummingbot/connector/exchange/backpack/backpack_exchange.py`
**Lines**: 685-689

#### Current Problem:
```python
timestamp_ms = int(time.time() * 1000)
client_id = timestamp_ms % 1000000000  # Can cause collisions
```

#### Steps:
1. [ ] Write test for order ID uniqueness (1000 rapid orders)
2. [ ] Implement counter-based unique ID generation
3. [ ] Ensure IDs fit within uint32 range (0-4294967295)
4. [ ] Add thread-safety if needed
5. [ ] Run stress test to verify no collisions

#### Implementation:
```python
def _generate_unique_client_id(self) -> int:
    if not hasattr(self, '_order_counter'):
        self._order_counter = 0
    
    timestamp_part = int(time.time() * 1000) % 1000000
    counter_part = self._order_counter % 1000
    self._order_counter += 1
    
    client_id = timestamp_part * 1000 + counter_part
    return client_id % 4294967296
```

#### Test Case:
```python
def test_unique_order_id_generation():
    # Generate 1000 IDs rapidly
    # Verify all are unique
    # Verify all fit in uint32
    # Test thread safety
```

### Task 2.2: Fix Error Response Handling
**Status**: [ ] Not Started
**File**: `hummingbot/connector/exchange/backpack/backpack_exchange.py`
**Lines**: 719-732

#### Steps:
1. [ ] Write test for various error responses
2. [ ] Create error code mapping dictionary
3. [ ] Implement proper error parsing
4. [ ] Remove fragile string matching
5. [ ] Add comprehensive error handling

#### Test Case:
```python
def test_error_response_handling():
    # Test various error codes
    # Test unknown error handling
    # Test malformed responses
    # Verify appropriate exceptions raised
```

### Task 2.3: Fix Order Cancellation Race Condition
**Status**: [ ] Not Started
**File**: `hummingbot/connector/exchange/backpack/backpack_exchange.py`
**Lines**: 771-791

#### Steps:
1. [ ] Write test for immediate cancellation after placement
2. [ ] Implement retry mechanism with timeout
3. [ ] Add proper async waiting for exchange_order_id
4. [ ] Handle timeout gracefully with fallback to client_id
5. [ ] Test under various timing conditions

#### Implementation:
```python
async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
    max_retries = 3
    retry_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            exchange_order_id = await asyncio.wait_for(
                tracked_order.get_exchange_order_id(),
                timeout=5.0
            )
            if exchange_order_id:
                # Use exchange_order_id
                break
        except asyncio.TimeoutError:
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
            else:
                # Fall back to client_id
```

#### Test Case:
```python
def test_order_cancellation_race_condition():
    # Place order and immediately cancel
    # Test with delayed exchange_order_id
    # Test timeout and fallback
    # Verify successful cancellation
```

### Task 2.4: Fix Balance Calculation Logic
**Status**: [ ] Not Started
**File**: `hummingbot/connector/exchange/backpack/backpack_exchange.py`
**Lines**: 384-445

#### Current Problem:
- Using `max()` instead of proper reconciliation
- Mixing spot and collateral accounts
- No consideration for locked amounts

#### Steps:
1. [ ] Write test for balance reconciliation
2. [ ] Separate spot and collateral balances
3. [ ] Implement proper balance merging logic
4. [ ] Account for locked/reserved amounts
5. [ ] Test with various account configurations

#### Implementation:
```python
async def _update_balances(self):
    spot_balances = await self._fetch_spot_balances()
    collateral_balances = await self._fetch_collateral_balances()
    
    self._account_balances = {
        "spot": spot_balances,
        "collateral": collateral_balances,
        "total": self._calculate_total_balances(spot_balances, collateral_balances)
    }
    
    self._account_available_balances = self._calculate_available_balances()
```

#### Test Case:
```python
def test_balance_calculation():
    # Test spot only balances
    # Test collateral only balances
    # Test mixed balances
    # Test with open orders (locked amounts)
    # Verify no double counting
```

### Task 2.5: Implement Order State Validation
**Status**: [ ] Not Started
**File**: `hummingbot/connector/exchange/backpack/backpack_exchange.py`

#### Steps:
1. [ ] Write test for state transitions
2. [ ] Define valid state transition map
3. [ ] Implement validation function
4. [ ] Add logging for invalid transitions
5. [ ] Enforce state machine rules

#### Implementation:
```python
VALID_STATE_TRANSITIONS = {
    OrderState.PENDING_CREATE: [OrderState.OPEN, OrderState.FAILED],
    OrderState.OPEN: [OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELED],
    OrderState.PARTIALLY_FILLED: [OrderState.FILLED, OrderState.CANCELED],
}

def _validate_order_state_transition(self, order: InFlightOrder, new_state: OrderState):
    current_state = order.current_state
    valid_transitions = self.VALID_STATE_TRANSITIONS.get(current_state, [])
    
    if new_state not in valid_transitions:
        self.logger().error(f"Invalid transition: {current_state} -> {new_state}")
        return False
    return True
```

#### Test Case:
```python
def test_order_state_validation():
    # Test valid transitions
    # Test invalid transitions are blocked
    # Test all state paths
    # Verify proper error logging
```

### Task 2.6: Add Idempotency for Order Operations
**Status**: [ ] Not Started
**File**: `hummingbot/connector/exchange/backpack/backpack_exchange.py`

#### Steps:
1. [ ] Write test for idempotent operations
2. [ ] Implement idempotency key generation
3. [ ] Cache operation results
4. [ ] Handle duplicate requests
5. [ ] Test with network retries

#### Test Case:
```python
def test_order_operation_idempotency():
    # Test duplicate order placement prevented
    # Test duplicate cancellation handled
    # Test network retry scenarios
    # Verify consistent results
```

## Acceptance Criteria
- [ ] Zero order ID collisions in 10,000 rapid orders
- [ ] All error codes properly handled
- [ ] Order cancellation works immediately after placement
- [ ] Balance calculations accurate for all account types
- [ ] Invalid state transitions prevented
- [ ] Idempotent operations implemented
- [ ] All tests pass with >90% coverage

## Notes
- Must maintain compatibility with existing order tracking
- Consider adding order reconciliation on reconnection
- Future: Implement circuit breaker for repeated failures