import threading
import pandas as pd
from typing import Dict, Optional
# ============ Market Data ============

# List of all tokens being tracked
all_tokens = []

# Mapping between tokens in the same market (YES->NO, NO->YES)
REVERSE_TOKENS = {}  

# Order book data for all markets
order_book_data = {}  

# Market configuration data from Google Sheets
df = None

# Filtered markets after applying custom selection logic
selected_markets_df = None

markets_with_positions = None

# Position sizing information for each market
# Format: {condition_id: PositionSizeResult}
market_trade_sizes = {}

# Available cash liquidity for trading (USDC balance)
available_liquidity: Optional[float] = None  

# ============ Client & Parameters ============

# Polymarket client instance
client = None

# Trading parameters from Google Sheets
params = {}

# Lock for thread-safe trading operations
lock = threading.Lock()

# ============ Trading State ============

# Tracks trades that have been matched but not yet mined
# Format: {"token_side": {trade_id1, trade_id2, ...}}
performing = {}

# Timestamps for when trades were added to performing
# Used to clear stale trades
performing_timestamps = {}

# Timestamps for when positions were last updated
last_trade_update = {}

# Current open orders for each token
# Format: {token_id: {'buy': {price, size}, 'sell': {price, size}}}
orders = {}

# Current positions for each token
# Format: {token_id: {'size': float, 'avgPrice': float}}
positions = {}


def get_active_markets():
    """Return the union of selected markets and markets with positions.

    When we have open positions, ensure those markets are included even if they
    are not currently selected by the filter. Duplicates are removed by
    `condition_id` while keeping the first occurrence.
    """
    combined_markets = selected_markets_df

    # Treat None as empty for robustness
    has_markets_with_positions = (
        markets_with_positions is not None and len(markets_with_positions) > 0
    )

    if has_markets_with_positions:
        if combined_markets is not None:
            combined_markets = pd.concat([combined_markets, markets_with_positions]).drop_duplicates(
                subset=['condition_id'], keep='first'
            )
        else:
            combined_markets = markets_with_positions

    return combined_markets
