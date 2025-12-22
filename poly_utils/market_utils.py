from configuration import TCNF

def calculate_market_imbalance(bids_df, asks_df, midpoint):
    # The window to look for imbalance is the hybrid of fixed number of price levels,
    # and a fixed spread size calculated from the percentage of midpoint
    bids_sorted = bids_df[bids_df['price'] <= midpoint].sort_values('price', ascending=False)
    level_window_lower = bids_sorted['price'].head(TCNF.MARKET_DEPTH_CALC_LEVELS).min() if not bids_sorted.empty else midpoint

    asks_sorted = asks_df[asks_df['price'] >= midpoint].sort_values('price', ascending=True)
    level_window_upper = asks_sorted['price'].head(TCNF.MARKET_DEPTH_CALC_LEVELS).max() if not asks_sorted.empty else midpoint

    spread_size = min(midpoint, 1-midpoint) * TCNF.MARKET_DEPTH_CALC_PCT
    pct_window_lower = midpoint - spread_size/2
    pct_window_upper = midpoint + spread_size/2

    window_lower = max(level_window_lower, pct_window_lower)
    window_upper = min(level_window_upper, pct_window_upper)

    bids_in_window = bids_df[(bids_df['price'] >= window_lower) & (bids_df['price'] <= window_upper)]
    bids_size_in_window = bids_in_window['size'].sum()
    asks_in_window = asks_df[(asks_df['price'] >= window_lower) & (asks_df['price'] <= window_upper)]
    asks_size_in_window = asks_in_window['size'].sum()

    imbalance = (bids_size_in_window - asks_size_in_window) / (bids_size_in_window + asks_size_in_window)
    return imbalance


def calculate_market_depth(bids_df, asks_df, midpoint):
    """Calculate depth_bids and depth_asks using hybrid level/percentage approach"""
    depth_bids = 0
    depth_asks = 0
    
    # Calculate window for YES side (bids below midpoint)
    # Level-based window
    bids_sorted = bids_df[bids_df['price'] <= midpoint].sort_values('price', ascending=False)
    level_window_lower_yes = bids_sorted['price'].head(TCNF.MARKET_DEPTH_CALC_LEVELS).min() if not bids_sorted.empty else midpoint
    
    # Percentage-based window
    spread_size = min(midpoint, 1-midpoint) * TCNF.MARKET_DEPTH_CALC_PCT
    pct_window_lower_yes = midpoint - spread_size
    
    # Take the intersection (max of lower bounds, midpoint as upper bound)
    window_lower_yes = max(level_window_lower_yes, pct_window_lower_yes)
    window_upper_yes = midpoint
    
    # Calculate depth_bids
    if not bids_df.empty:
        filtered_bids = bids_df[(bids_df['price'] >= window_lower_yes) & (bids_df['price'] <= window_upper_yes)]
        depth_bids = filtered_bids['size'].sum()
    
    # Calculate window for NO side (asks above midpoint)
    # Level-based window
    asks_sorted = asks_df[asks_df['price'] >= midpoint].sort_values('price', ascending=True)
    level_window_upper_no = asks_sorted['price'].head(TCNF.MARKET_DEPTH_CALC_LEVELS).max() if not asks_sorted.empty else midpoint
    
    # Percentage-based window
    pct_window_upper_no = midpoint + spread_size
    
    # Take the intersection (midpoint as lower bound, min of upper bounds)
    window_lower_no = midpoint
    window_upper_no = min(level_window_upper_no, pct_window_upper_no)
    
    # Calculate depth_asks
    if not asks_df.empty:
        filtered_asks = asks_df[(asks_df['price'] >= window_lower_no) & (asks_df['price'] <= window_upper_no)]
        depth_asks = filtered_asks['size'].sum()
    
    return depth_bids, depth_asks
    