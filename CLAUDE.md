# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Poly-Maker is a sophisticated market making bot for Polymarket prediction markets. It provides automated liquidity by maintaining buy/sell orders with configurable risk parameters and real-time monitoring.

## Architecture

The codebase is organized into several interconnected modules:

- **`poly_data/`**: Core trading engine with market making logic
  - `polymarket_client.py`: Polymarket API client wrapper
  - `global_state.py`: Centralized application state management
  - `websocket_handlers.py`: Real-time market data via WebSocket connections
  - `trading_utils.py`: Order pricing, sizing, and execution logic
  - `data_processing.py`: Market data filtering and processing
  - `data_utils.py`: Position/order synchronization with Polymarket API

- **`poly_merger/`**: Node.js utility for position consolidation (reduces gas fees)
- **`poly_stats/`**: Account performance tracking and analytics
- **`poly_utils/`**: Shared utilities, primarily Google Sheets integration
- **`data_updater/`**: Market discovery and data collection (separate process)

## Key Dependencies

- **Python 3.9+** with py-clob-client for Polymarket integration
- **Node.js** for poly_merger position consolidation
- **Google Sheets API** for configuration and market selection
- **WebSocket connections** for real-time market data

## Development Commands

### Setup and Installation
```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies (creates .venv automatically)
uv sync

# Install with dev dependencies
uv sync --all-extras

# Install Node.js dependencies for the merger
cd poly_merger && npm install && cd ..
```

### Running the Bot
```bash
# Update market data first (run continuously in background)
uv run python update_markets.py

# Start the main market making bot
uv run python main.py
```

### Utility Scripts
```bash
# Update account statistics
uv run python update_stats.py

# Sync Logan logging library
./scripts/sync_logan.sh
```

### Testing
The project uses pytest for testing:
```bash
uv run pytest
```

### Adding Dependencies
```bash
# Add a runtime dependency
uv add <package-name>

# Add a dev dependency
uv add --dev <package-name>
```

## Configuration

The bot is configured via Google Sheets with these worksheets:
- **Selected Markets**: Markets to actively trade
- **All Markets**: Complete Polymarket market database
- **Hyperparameters**: Trading parameters (spreads, position limits, etc.)
- **Volatility Markets**: Markets filtered by volatility metrics

## State Management

The application uses a centralized state management system (`global_state.py`) that tracks:
- Real-time order books (`all_data`)
- Current positions and orders (`positions`, `orders`)
- Trading locks to prevent race conditions (`performing`, `performing_timestamps`)
- Market configuration from Google Sheets (`df`, `params`)

## WebSocket Architecture

Two concurrent WebSocket connections handle real-time data:
- **Market WebSocket**: Order book updates for all tracked tokens
- **User WebSocket**: Account-specific updates (fills, position changes)

The main event loop maintains these connections and handles reconnections automatically.

## Trading Logic Flow

1. **Initialization**: Fetch positions, orders, and market data
2. **Background Updates**: Periodic sync every 5-30 seconds
3. **Real-time Processing**: WebSocket events trigger order adjustments
4. **Risk Management**: Position limits and stale trade cleanup
5. **Order Management**: Dynamic pricing based on volatility and spreads

## Environment Variables

Required in `.env`:
- `PK`: Private key for Polymarket transactions
- `BROWSER_ADDRESS`: Wallet address
- `SPREADSHEET_URL`: Google Sheets configuration URL

## Position Merging

The `poly_merger/` module consolidates positions to optimize gas usage:
```bash
cd poly_merger
node merge.js
```