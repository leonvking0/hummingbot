# Task: WebSocket Implementation Reliability Fixes

## Related Issue
- **File**: `/Users/han/github/hummingbot/issues/websocket-implementation-issues.md`
- **Severity**: HIGH
- **Priority**: HIGH

## Overview
Fix WebSocket implementation issues including missing error handling, no auto-reconnection, incorrect timestamp conversions, and lack of heartbeat mechanism that could lead to data loss and connection instability.

## Tasks Breakdown

### Task 3.1: Add Error Handling in Message Processing
**Status**: [ ] Not Started
**File**: `hummingbot/connector/exchange/backpack/backpack_api_order_book_data_source.py`
**Lines**: 252-264

#### Steps:
1. [ ] Write test for malformed message handling
2. [ ] Wrap message parsing in try-catch blocks
3. [ ] Add error logging with context
4. [ ] Ensure loop continues on individual message failure
5. [ ] Test with various malformed messages

#### Implementation:
```python
async def _process_websocket_messages(self, websocket_assistant: WSAssistant):
    async for ws_response in websocket_assistant.iter_messages():
        try:
            data = ws_response.data
            if isinstance(data, dict) and data.get("stream"):
                channel = self._channel_originating_message(data)
                if channel == self._diff_messages_queue_key:
                    await self._parse_order_book_diff_message(data, self._message_queue[channel])
                elif channel == self._trade_messages_queue_key:
                    await self._parse_trade_message(data, self._message_queue[channel])
        except Exception as e:
            self.logger().error(f"Error processing WebSocket message: {e}", exc_info=True)
            # Continue processing other messages
```

#### Test Case:
```python
def test_websocket_error_handling():
    # Send malformed JSON
    # Send messages with missing fields
    # Send invalid data types
    # Verify processing continues
    # Verify errors are logged
```

### Task 3.2: Fix Timestamp Conversion Inconsistency
**Status**: [ ] Not Started
**File**: `hummingbot/connector/exchange/backpack/backpack_api_order_book_data_source.py`
**Line**: 228

#### Current Problem:
```python
# Inconsistent: comment says microseconds but fallback is milliseconds
timestamp = data.get("E", time.time() * 1000) / 1e6
```

#### Steps:
1. [ ] Write test for timestamp consistency
2. [ ] Verify Backpack's timestamp format (microseconds)
3. [ ] Fix conversion to use consistent units
4. [ ] Test timestamp ordering
5. [ ] Verify no time-based issues

#### Implementation:
```python
# Backpack uses microseconds, convert to seconds consistently
timestamp = data.get("E", time.time() * 1e6) / 1e6
```

#### Test Case:
```python
def test_timestamp_conversion():
    # Test with provided timestamps
    # Test with fallback timestamps
    # Verify consistent units
    # Test ordering preservation
```

### Task 3.3: Implement Auto-Reconnection with Exponential Backoff
**Status**: [ ] Not Started
**File**: `hummingbot/connector/exchange/backpack/backpack_api_order_book_data_source.py`
**Lines**: 265-269

#### Steps:
1. [ ] Write test for reconnection logic
2. [ ] Implement exponential backoff (1s, 2s, 4s, 8s, max 30s)
3. [ ] Add max reconnection attempts (10)
4. [ ] Log reconnection attempts
5. [ ] Test various disconnection scenarios

#### Implementation:
```python
async def _on_order_stream_interruption(self, websocket_assistant: Optional[WSAssistant]):
    if websocket_assistant:
        await websocket_assistant.disconnect()
    self._ws_assistant = None
    
    # Attempt reconnection with exponential backoff
    for attempt in range(self.MAX_RECONNECT_ATTEMPTS):
        delay = min(2 ** attempt, 30)  # Max 30 seconds
        self.logger().info(f"Reconnection attempt {attempt + 1} in {delay}s")
        await asyncio.sleep(delay)
        
        try:
            await self._subscribe_to_order_book_streams()
            self.logger().info("Successfully reconnected to WebSocket")
            break
        except Exception as e:
            self.logger().error(f"Reconnection attempt {attempt + 1} failed: {e}")
            if attempt == self.MAX_RECONNECT_ATTEMPTS - 1:
                self.logger().critical("Max reconnection attempts reached")
```

#### Test Case:
```python
def test_websocket_reconnection():
    # Simulate connection drop
    # Verify reconnection attempts
    # Test exponential backoff timing
    # Test max attempts limit
    # Verify successful reconnection
```

### Task 3.4: Implement Heartbeat/Keepalive Mechanism
**Status**: [ ] Not Started
**File**: `hummingbot/connector/exchange/backpack/backpack_api_order_book_data_source.py`

#### Steps:
1. [ ] Write test for heartbeat functionality
2. [ ] Implement ping/pong mechanism
3. [ ] Use existing WS_HEARTBEAT_INTERVAL constant (30s)
4. [ ] Detect stale connections
5. [ ] Trigger reconnection on heartbeat failure

#### Implementation:
```python
async def _send_heartbeat(self, websocket_assistant: WSAssistant):
    """Send periodic heartbeat to keep connection alive"""
    while self._ws_assistant:
        try:
            await asyncio.sleep(CONSTANTS.WS_HEARTBEAT_INTERVAL)
            if self._ws_assistant:
                await websocket_assistant.send({"op": "ping"})
                self._last_heartbeat = time.time()
        except Exception as e:
            self.logger().error(f"Error sending heartbeat: {e}")
            await self._on_order_stream_interruption(websocket_assistant)
            break

async def _monitor_heartbeat(self):
    """Monitor heartbeat responses"""
    while self._ws_assistant:
        await asyncio.sleep(CONSTANTS.WS_HEARTBEAT_INTERVAL * 2)
        if time.time() - self._last_heartbeat > CONSTANTS.WS_HEARTBEAT_INTERVAL * 2:
            self.logger().warning("Heartbeat timeout, reconnecting...")
            await self._on_order_stream_interruption(self._ws_assistant)
```

#### Test Case:
```python
def test_websocket_heartbeat():
    # Test heartbeat sending
    # Test heartbeat timeout detection
    # Test reconnection on heartbeat failure
    # Verify keepalive works
```

### Task 3.5: Handle Message Queue Overflow
**Status**: [ ] Not Started
**File**: `hummingbot/connector/exchange/backpack/backpack_api_order_book_data_source.py`
**Lines**: 235, 250

#### Steps:
1. [ ] Write test for queue overflow scenarios
2. [ ] Handle asyncio.QueueFull exception
3. [ ] Add queue size monitoring
4. [ ] Implement backpressure or larger queue
5. [ ] Log dropped messages

#### Implementation:
```python
try:
    message_queue.put_nowait(order_book_msg)
except asyncio.QueueFull:
    self.logger().warning(f"Message queue full for {trading_pair}, dropping message")
    # Consider implementing a larger queue or backpressure mechanism
    self._dropped_messages_count += 1
    if self._dropped_messages_count > self.MAX_DROPPED_MESSAGES:
        self.logger().error("Too many dropped messages, reconnecting...")
        await self._on_order_stream_interruption(self._ws_assistant)
```

#### Test Case:
```python
def test_message_queue_overflow():
    # Fill queue to capacity
    # Send additional messages
    # Verify overflow handling
    # Test recovery mechanism
```

### Task 3.6: Add WebSocket State Management
**Status**: [ ] Not Started
**File**: `hummingbot/connector/exchange/backpack/backpack_api_order_book_data_source.py`

#### Steps:
1. [ ] Write test for state transitions
2. [ ] Define WebSocket state enum
3. [ ] Track connection state
4. [ ] Prevent operations on invalid states
5. [ ] Add state logging

#### Implementation:
```python
class WebSocketState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    RECONNECTING = "reconnecting"

    @property
    def is_connected(self):
        return self == WebSocketState.CONNECTED
```

#### Test Case:
```python
def test_websocket_state_management():
    # Test state transitions
    # Test operations blocked in invalid states
    # Test state consistency
    # Verify proper state logging
```

## Acceptance Criteria
- [ ] WebSocket continues processing after malformed messages
- [ ] Timestamps consistently use microseconds
- [ ] Auto-reconnection succeeds within 10 attempts
- [ ] Heartbeat keeps connection alive for hours
- [ ] Message queue overflow handled gracefully
- [ ] WebSocket state properly tracked
- [ ] 100% uptime in 24-hour test
- [ ] All tests pass with >85% coverage

## Notes
- Must maintain compatibility with existing WebSocket protocol
- Consider adding metrics for monitoring WebSocket health
- Future: Implement message sequence validation