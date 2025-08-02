# Configuration and Initialization Issues

## Issue Summary
The Backpack Exchange connector has several configuration and initialization problems that could lead to incorrect setup, confusion about operating modes, and initialization failures.

## Severity: HIGH

## Detailed Findings

### 1. Ambiguous Trading Mode Determination
**Location**: `backpack_exchange.py:58-64`

```python
# Enable trading if API credentials are provided, unless explicitly set
# If trading_required is explicitly passed (True or False), use that value
# Otherwise, enable trading if API credentials are provided
if trading_required is not None and isinstance(trading_required, bool):
    self._trading_required = trading_required
else:
    self._trading_required = bool(api_key and api_secret)
```

**Problem**: Complex logic for determining trading mode creates confusion:
- `trading_required` parameter can be None, True, or False
- Auto-detection based on credentials can be misleading
- Demo mode determination is coupled with credential presence

**Impact**:
- Users unsure which mode is active
- Potential for accidental trading in production
- Configuration errors

**Recommendation**:
```python
def __init__(self,
            client_config_map: "ClientConfigAdapter",
            api_key: str = "",
            api_secret: str = "",
            trading_pairs: Optional[List[str]] = None,
            mode: str = "public",  # "public", "trading", "demo"
            domain: str = CONSTANTS.DEFAULT_DOMAIN):
    
    # Clear mode determination
    if mode not in ["public", "trading", "demo"]:
        raise ValueError(f"Invalid mode: {mode}. Must be 'public', 'trading', or 'demo'")
    
    self._mode = mode
    
    # Validate configuration for mode
    if mode == "trading" and (not api_key or not api_secret):
        raise ValueError("Trading mode requires API credentials")
    
    if mode == "demo":
        self.logger().warning("Running in DEMO MODE - no real trades will be executed")
    
    self._trading_required = (mode == "trading")
    self._demo_mode = (mode == "demo")
```

### 2. Missing Configuration Validation
**Location**: Initialization code

**Problem**: No validation of configuration parameters:
- API keys format not validated
- Trading pairs not validated against exchange
- Domain validity not checked

**Impact**:
- Runtime failures instead of early detection
- Poor user experience
- Difficult debugging

**Recommendation**:
```python
def _validate_configuration(self):
    """Validate configuration parameters"""
    
    # Validate API credentials format
    if self._api_key:
        try:
            # Check if it's valid base64
            base64.b64decode(self._api_key)
        except Exception:
            raise ValueError("API key must be base64 encoded")
    
    if self._api_secret:
        try:
            # Check if it's valid base64 ED25519 key
            key_bytes = base64.b64decode(self._api_secret)
            if len(key_bytes) != 32:  # ED25519 key size
                raise ValueError("API secret must be 32-byte ED25519 key")
        except Exception as e:
            raise ValueError(f"Invalid API secret format: {e}")
    
    # Validate trading pairs format
    for pair in self._trading_pairs:
        if not re.match(r'^[A-Z]+-[A-Z]+$', pair):
            raise ValueError(f"Invalid trading pair format: {pair}")
    
    # Validate domain
    if self._domain not in CONSTANTS.VALID_DOMAINS:
        raise ValueError(f"Invalid domain: {self._domain}")
```

### 3. Initialization Race Conditions
**Location**: `start_network` method

```python
async def start_network(self):
    await self.stop_network()
    self.order_book_tracker.start()
    
    if not self.trading_pair_symbol_map_ready():
        await self._initialize_trading_pair_symbol_map()
    
    if self.is_trading_required:
        try:
            await self._update_trading_rules()
```

**Problem**: No proper synchronization of initialization steps:
- Components might start before dependencies are ready
- No rollback on partial initialization failure
- Race conditions between parallel initializations

**Impact**:
- Intermittent initialization failures
- Inconsistent state
- Difficult to reproduce bugs

**Recommendation**:
```python
async def start_network(self):
    """Initialize network components with proper sequencing"""
    
    initialization_steps = [
        ("Stopping existing network", self.stop_network),
        ("Initializing trading pairs", self._initialize_trading_pair_symbol_map),
        ("Starting order book tracker", self._start_order_book_tracker),
        ("Loading trading rules", self._update_trading_rules),
        ("Updating balances", self._update_balances),
        ("Starting user stream", self._start_user_stream),
    ]
    
    completed_steps = []
    
    try:
        for step_name, step_func in initialization_steps:
            self.logger().info(f"Initialization: {step_name}")
            await step_func()
            completed_steps.append(step_func)
            
    except Exception as e:
        self.logger().error(f"Initialization failed at '{step_name}': {e}")
        
        # Rollback completed steps
        for step in reversed(completed_steps):
            try:
                await self._rollback_step(step)
            except Exception as rollback_error:
                self.logger().error(f"Rollback failed: {rollback_error}")
        
        raise InitializationError(f"Failed to initialize: {e}")
```

### 4. Hardcoded Configuration Values
**Location**: Throughout the codebase

```python
# Hardcoded limits
ORDER_BOOK_DEPTH_LIMIT = 1000
DEFAULT_REQUEST_WINDOW = 5000

# Hardcoded decimals
DEFAULT_PRICE_DECIMALS = 8
DEFAULT_QUANTITY_DECIMALS = 8
```

**Problem**: Configuration values hardcoded instead of configurable.

**Impact**:
- Cannot adjust for different requirements
- Poor flexibility
- Requires code changes for configuration

**Recommendation**:
```python
# config/backpack_config.py
@dataclass
class BackpackConfig:
    """Configuration for Backpack Exchange connector"""
    
    # API Configuration
    request_window_ms: int = 5000
    max_request_window_ms: int = 60000
    
    # Order Book Configuration
    order_book_depth_limit: int = 1000
    order_book_refresh_time: float = 1.0
    
    # Trading Configuration
    default_price_decimals: int = 8
    default_quantity_decimals: int = 8
    
    # WebSocket Configuration
    ws_heartbeat_interval: int = 30
    ws_heartbeat_timeout: int = 60
    ws_reconnect_attempts: int = 5
    
    # Performance Configuration
    message_queue_size: int = 1000
    max_concurrent_requests: int = 10
    
    @classmethod
    def from_file(cls, path: str) -> "BackpackConfig":
        """Load configuration from YAML file"""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)
```

### 5. No Environment-Specific Configuration
**Location**: Configuration system

**Problem**: No separation between development, staging, and production configurations.

**Impact**:
- Risk of using wrong configuration
- Manual configuration changes for different environments
- Testing difficulties

**Recommendation**:
```python
class EnvironmentConfig:
    """Environment-specific configuration"""
    
    ENVIRONMENTS = {
        "development": {
            "domain": "testnet",
            "log_level": "DEBUG",
            "rate_limit_factor": 0.5,
        },
        "staging": {
            "domain": "testnet",
            "log_level": "INFO",
            "rate_limit_factor": 0.8,
        },
        "production": {
            "domain": "mainnet",
            "log_level": "WARNING",
            "rate_limit_factor": 1.0,
        }
    }
    
    @classmethod
    def get_config(cls, environment: str = None) -> Dict:
        """Get configuration for specified environment"""
        if environment is None:
            environment = os.getenv("HUMMINGBOT_ENVIRONMENT", "development")
        
        if environment not in cls.ENVIRONMENTS:
            raise ValueError(f"Unknown environment: {environment}")
        
        return cls.ENVIRONMENTS[environment]
```

### 6. Missing Configuration Migration
**Location**: Configuration loading

**Problem**: No mechanism to handle configuration schema changes between versions.

**Impact**:
- Breaking changes on updates
- Manual configuration updates required
- User frustration

**Recommendation**:
```python
class ConfigMigration:
    """Handle configuration migration between versions"""
    
    MIGRATIONS = {
        "1.0.0": lambda c: c,  # Initial version
        "1.1.0": lambda c: {**c, "new_field": "default"},  # Added field
        "1.2.0": lambda c: {k: v for k, v in c.items() if k != "old_field"},  # Removed field
    }
    
    @classmethod
    def migrate(cls, config: Dict, from_version: str, to_version: str) -> Dict:
        """Migrate configuration from one version to another"""
        versions = sorted(cls.MIGRATIONS.keys())
        
        start_idx = versions.index(from_version)
        end_idx = versions.index(to_version)
        
        for version in versions[start_idx + 1:end_idx + 1]:
            migration = cls.MIGRATIONS[version]
            config = migration(config)
            
        return config
```

## Steps to Reproduce

1. Initialize connector without API keys - observe mode confusion
2. Provide invalid API credentials - observe late failure
3. Interrupt initialization - observe partial state
4. Try to modify hardcoded limits - requires code changes
5. Switch between environments - manual configuration required

## Priority Actions

1. **IMMEDIATE**: Clarify and simplify mode determination
2. **HIGH**: Add configuration validation on initialization
3. **HIGH**: Fix initialization race conditions
4. **MEDIUM**: Make hardcoded values configurable
5. **MEDIUM**: Add environment-specific configuration
6. **LOW**: Implement configuration migration

## Additional Recommendations

1. Create configuration schema with JSON Schema
2. Add configuration validation CLI command
3. Implement configuration hot-reloading
4. Add configuration templates for common scenarios
5. Create configuration documentation
6. Add configuration tests