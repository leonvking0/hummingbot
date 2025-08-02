# WebSocket Implementation Issues in Backpack Exchange Connector

## Issue Summary
The WebSocket implementation in the Backpack Exchange connector has multiple issues that could lead to data loss, connection instability, and incorrect market data processing.

## Severity: HIGH

## Detailed Findings

### 1. Missing Error Handling in WebSocket Message Processing
**Location**: `backpack_api_order_book_data_source.py:252-264`

```python
async def _process_websocket_messages(self, websocket_assistant: WSAssistant):
    async for ws_response in websocket_assistant.iter_messages():
        data = ws_response.data
        if isinstance(data, dict) and data.get("stream"):
            channel = self._channel_originating_message(data)
            if channel == self._diff_messages_queue_key:
                await self._parse_order_book_diff_message(data, self._message_queue[channel])
            elif channel == self._trade_messages_queue_key:
                await self._parse_trade_message(data, self._message_queue[channel])
```

**Problem**: No error handling for malformed messages or parsing failures. If a message fails to parse, the entire WebSocket processing loop could crash.

**Impact**: 
- Connection drops on malformed messages
- Loss of market data stream
- Order book desynchronization

**Recommendation**:
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

### 2. Incorrect Timestamp Conversion
**Location**: `backpack_api_order_book_data_source.py:228`

```python
# Get timestamp from data or use current time
timestamp = data.get("E", time.time() * 1000) / 1e6  # Convert microseconds to seconds
```

**Problem**: The comment says "Convert microseconds to seconds" but divides by 1e6, which would be for microseconds. However, the fallback `time.time() * 1000` produces milliseconds, creating an inconsistency.

**Impact**: Incorrect timestamps could lead to:
- Order book updates being processed out of order
- Incorrect age calculations for market data
- Trading decisions based on stale data

**Recommendation**:
```python
# Backpack uses microseconds, convert to seconds consistently
timestamp = data.get("E", time.time() * 1e6) / 1e6
```

### 3. No Heartbeat/Keepalive Implementation
**Location**: Throughout WebSocket implementation

**Problem**: Despite constants defined for heartbeat (`WS_HEARTBEAT_INTERVAL = 30`), there's no actual implementation of WebSocket ping/pong or keepalive mechanism.

**Impact**:
- Silent connection drops
- Stale connections consuming resources
- Delayed detection of network issues

**Recommendation**: Implement proper heartbeat mechanism:
```python
async def _send_heartbeat(self, websocket_assistant: WSAssistant):
    while True:
        try:
            await asyncio.sleep(CONSTANTS.WS_HEARTBEAT_INTERVAL)
            await websocket_assistant.send({"op": "ping"})
        except Exception as e:
            self.logger().error(f"Error sending heartbeat: {e}")
            break
```

### 4. Lack of Reconnection Logic
**Location**: `backpack_api_order_book_data_source.py:265-269`

```python
async def _on_order_stream_interruption(self, websocket_assistant: Optional[WSAssistant]):
    """Clean up on websocket interruption"""
    if websocket_assistant:
        await websocket_assistant.disconnect()
    self._ws_assistant = None
```

**Problem**: When WebSocket connection is interrupted, it only cleans up but doesn't attempt to reconnect.

**Impact**:
- Manual intervention required to restore data feed
- Extended periods without market data
- Trading strategies operating on stale data

**Recommendation**: Implement exponential backoff reconnection:
```python
async def _on_order_stream_interruption(self, websocket_assistant: Optional[WSAssistant]):
    if websocket_assistant:
        await websocket_assistant.disconnect()
    self._ws_assistant = None
    
    # Attempt reconnection with exponential backoff
    for attempt in range(self.MAX_RECONNECT_ATTEMPTS):
        await asyncio.sleep(2 ** attempt)
        try:
            await self._subscribe_to_order_book_streams()
            break
        except Exception as e:
            self.logger().error(f"Reconnection attempt {attempt + 1} failed: {e}")
```

### 5. Message Queue Overflow Risk
**Location**: `backpack_api_order_book_data_source.py:235, 250`

```python
message_queue.put_nowait(order_book_msg)
```

**Problem**: Using `put_nowait` without handling `asyncio.QueueFull` exception. If the queue fills up (processing slower than incoming messages), messages will be lost.

**Impact**:
- Silent message loss during high volume periods
- Order book gaps
- Incorrect market state

**Recommendation**:
```python
try:
    message_queue.put_nowait(order_book_msg)
except asyncio.QueueFull:
    self.logger().warning(f"Message queue full, dropping message for {trading_pair}")
    # Consider implementing a larger queue or backpressure mechanism
```

### 6. Stream Subscription Race Condition
**Location**: WebSocket subscription logic

**Problem**: No synchronization between subscription request and confirmation. The code assumes subscriptions are successful immediately.

**Impact**:
- Missing initial market data
- Subscription failures going unnoticed
- Inconsistent market data state

**Recommendation**: Wait for subscription confirmation:
```python
async def _subscribe_to_stream(self, stream: str):
    subscription_request = {"method": "SUBSCRIBE", "params": [stream]}
    await self._ws_assistant.send(subscription_request)
    
    # Wait for subscription confirmation
    timeout = 5.0
    start_time = time.time()
    while time.time() - start_time < timeout:
        msg = await self._ws_assistant.receive()
        if msg.get("result") and stream in msg.get("result", []):
            return True
    raise TimeoutError(f"Subscription to {stream} timed out")
```

### 7. Missing WebSocket State Management
**Location**: Throughout WebSocket implementation

**Problem**: No tracking of WebSocket connection state (connecting, connected, disconnecting, disconnected).

**Impact**:
- Difficulty debugging connection issues
- Potential for operations on closed connections
- Race conditions during state transitions

**Recommendation**: Implement state machine for WebSocket connection:
```python
class WebSocketState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    
    @property
    def is_connected(self):
        return self == WebSocketState.CONNECTED
```

## Steps to Reproduce

1. Start the Backpack connector with WebSocket streams
2. Simulate network interruption (disconnect network briefly)
3. Observe that WebSocket doesn't reconnect automatically
4. Send malformed messages to test error handling
5. Monitor for timestamp inconsistencies in order book updates

## Priority Actions

1. **IMMEDIATE**: Add error handling to message processing loop
2. **HIGH**: Implement automatic reconnection with exponential backoff
3. **HIGH**: Fix timestamp conversion inconsistency
4. **MEDIUM**: Add heartbeat/keepalive mechanism
5. **MEDIUM**: Handle message queue overflow
6. **LOW**: Implement WebSocket state management

## Additional Recommendations

1. Add metrics for WebSocket health monitoring
2. Implement message sequence validation
3. Add integration tests for WebSocket edge cases
4. Consider implementing message deduplication
5. Add configurable queue sizes based on expected volume