import threading
from logan import Logan
import pandas as pd
from typing import TypeVar, Generic, cast
from sortedcontainers import SortedDict

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

# Order book data for all markets
order_book_data = {}  

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


def get_order_book_exclude_self(token: str) -> dict:
    """
    Get the order book for a token with the user's own orders excluded.
    
    This returns a copy of the order book where the user's own buy orders
    are subtracted from bids and sell orders are subtracted from asks.
    
    Args:
        token: The token ID to get the order book for
        
    Returns:
        Dict with 'bids' and 'asks' SortedDicts, excluding self orders
    """
    if token not in order_book_data:
        return {'bids': SortedDict(), 'asks': SortedDict()}
    
    # Create copies of the order book
    bids_copy = SortedDict(order_book_data[token]['bids'])
    asks_copy = SortedDict(order_book_data[token]['asks'])
    
    # Get user's orders for this token
    token_orders = orders.get(str(token), {})
    
    # Subtract buy orders from bids
    buy_order = token_orders.get('buy', {})
    if buy_order and buy_order.get('size', 0) > 0:
        buy_price = buy_order.get('price', 0)
        if buy_price in bids_copy:
            new_size = bids_copy[buy_price] - buy_order['size']
            if new_size <= 0:
                del bids_copy[buy_price]
            else:
                bids_copy[buy_price] = new_size
    
    # Subtract sell orders from asks
    sell_order = token_orders.get('sell', {})
    if sell_order and sell_order.get('size', 0) > 0:
        sell_price = sell_order.get('price', 0)
        if sell_price in asks_copy:
            new_size = asks_copy[sell_price] - sell_order['size']
            if new_size <= 0:
                del asks_copy[sell_price]
            else:
                asks_copy[sell_price] = new_size

    return {'bids': bids_copy, 'asks': asks_copy}
