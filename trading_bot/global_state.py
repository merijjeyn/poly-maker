import threading
import pandas as pd
from typing import TypeVar, Generic, cast

from trading_bot.polymarket_client import PolymarketClient

T = TypeVar('T')

class Global(Generic[T]):
    _value: T | None = None

    def __get__(self, obj, objtype=None) -> T:
        if self._value is None:
            raise RuntimeError("Uninitialized")
        return self._value
    
    def __set__(self, obj, value: T) -> None:
        self._value = value


# ============ Market Data ============

# List of all tokens being tracked
all_tokens = []

# Mapping between tokens in the same market (YES->NO, NO->YES)
REVERSE_TOKENS = {}

# Market configuration data from Google Sheets
df = cast(pd.DataFrame, Global[pd.DataFrame]())

# Filtered markets after applying custom selection logic
selected_markets_df = cast(pd.DataFrame, Global[pd.DataFrame]())

markets_with_positions = cast(pd.DataFrame, Global[pd.DataFrame]())

# Position sizing information for each market
# Format: {condition_id: PositionSizeResult}
market_trade_sizes = {}

# Available cash liquidity for trading (USDC balance)
available_liquidity: float = 0.0  

# ============ Client & Parameters ============

# Polymarket client instance
client = cast(PolymarketClient, Global[PolymarketClient]())

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


