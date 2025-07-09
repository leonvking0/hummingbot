# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hummingbot is an open-source framework for designing and deploying automated trading bots on centralized and decentralized exchanges. It uses Python as the primary language with Cython extensions for performance-critical components.

## Common Development Commands

### Setup and Build
```bash
# Create conda environment and install dependencies
./install

# Compile Cython extensions (required after code changes to .pyx files)
./compile
# or
make build
```

### Enter the python environment
```
conda activate hummingbot
```

### Running the Application
```bash
# Run main application
bin/hummingbot_quickstart.py

# Run V2 strategies
make run-v2
```

### Testing
```bash
# Run all tests
make test

# Run tests with coverage
make run_coverage
make report_coverage

# Run a specific test file
python -m pytest test/path/to/test_file.py

# Run a specific test
python -m pytest test/path/to/test_file.py::TestClass::test_method
```

### Code Quality
```bash
# Run linter
flake8 hummingbot/

# Format code (configured in pyproject.toml)
black hummingbot/
isort hummingbot/

# Pre-commit hooks are configured - install with:
pre-commit install
```

## High-Level Architecture

### Core Components

1. **Exchange Connectors** (`hummingbot/connector/`)
   - Standardized interfaces to trading venues
   - Types: `exchange/` (spot), `derivative/` (perps/futures), `gateway/` (DEX)
   - Each connector implements base classes for market data and trading operations

2. **Trading Strategies** (`hummingbot/strategy/` and `hummingbot/strategy_v2/`)
   - V1 strategies: Legacy framework in `strategy/`
   - V2 strategies: New framework with controllers in `controllers/`
   - Strategies inherit from base classes and implement trading logic

3. **Event System** (`hummingbot/core/`)
   - Clock-based event loop drives the application
   - Events propagate through listeners for order updates, trades, etc.
   - All components register event handlers

4. **Data Layer**
   - SQLAlchemy models in `hummingbot/model/`
   - Trade and order history persistence
   - Configuration storage

### Key Design Patterns

1. **Connector Architecture**: All exchange integrations follow a common interface pattern with:
   - Market data streaming
   - Order placement/cancellation
   - Balance tracking
   - Standardized event emission

2. **Strategy Framework**: Strategies implement lifecycle methods:
   - `start()`: Initialize strategy
   - `tick()`: Called every clock cycle
   - `stop()`: Cleanup
   - Event handlers for market updates

3. **Async Architecture**: Heavy use of asyncio for concurrent operations across multiple exchanges

### Configuration System

- YAML config files in `conf/` directory
- Strategy-specific config maps defined in each strategy module
- Encrypted storage for API keys and secrets

### Entry Points

- Main CLI: `bin/hummingbot_quickstart.py` -> `hummingbot/client/hummingbot_application.py`
- Imports resolve through the `hummingbot` package
- V2 strategies use controllers pattern with entry through `make run-v2`

### Performance Considerations

- Cython extensions (.pyx files) compile to C++ for performance
- Must run `./compile` after modifying any .pyx files
- Core data structures use optimized implementations

## Current Work: Backpack Exchange Integration

### Task Overview
Adding support for Backpack Exchange to Hummingbot, focusing on public API integration for order book and trade data.

### Todo List
A detailed todo list is maintained in `/todo.md` tracking all implementation tasks.

### Implementation Status
✅ **Completed**: BackpackExchange connector now successfully instantiates and can fetch:
- Trading rules and pairs
- Last traded prices
- Order book snapshots
- Real-time order book updates (WebSocket needs minor fix)

### Key Implementation Details
1. **Abstract Methods Implemented**:
   - `_is_order_not_found_during_cancelation_error`: Checks for INVALID_ORDER and RESOURCE_NOT_FOUND error codes
   - `_is_order_not_found_during_status_update_error`: Similar error code checking
   - `_update_trading_fees`: Currently returns pass (public API only)
   
2. **ClientConfigAdapter**: Exchange constructor now properly accepts and passes ClientConfigAdapter parameter

3. **User Stream**: Overridden to return None for public API only implementation

### Key Implementation Considerations
1. **Authentication**: Backpack uses ED25519 signatures instead of HMAC
2. **API Endpoints**:
   - Public markets: GET /api/v1/markets
   - Order book: GET /api/v1/depth?symbol={symbol}
   - Ticker: GET /api/v1/ticker?symbol={symbol}
3. **WebSocket Streams**: Format is `<type>.<symbol>` (e.g., `depth.SOL_USDC`)
4. **Trading Pair Format**: Uses underscores (SOL_USDC) instead of dashes

### API Documentation
Full API specification is available in `/api-doc/backpack.json`

# important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
