"""
Market Activity Metrics Calculation

This module calculates various activity metrics for Polymarket tokens:
1. Volume of activity from trades for the last N days
2. Decay weighted volume (more recent trades have higher emphasis)
3. Volume inside some fixed spread
4. Trade frequency (average in the last N days)
5. Number of unique traders and transactions

Note: In Polymarket terminology:
- A market has two tokens (Yes/No outcomes)
- Each token represents one side of the bet
- The trades API uses token_id in the 'market' parameter
"""

import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
from typing import Dict
from logan import Logan
from configuration import TCNF
from scipy import stats


def get_market_trades_data(condition_id: str) -> pd.DataFrame:
    """
    Fetch trades data for a given market (condition_id) over the configured lookback period.
    
    Args:
        condition_id: The condition ID (market ID) to fetch trades for
        
    Returns:
        DataFrame with trade data including timestamps, prices, sizes, etc.
    """
    try:
        # Calculate timestamp for lookback period
        # end_time = int(datetime.now().timestamp())
        # start_time = int((datetime.now() - timedelta(days=TCNF.ACTIVITY_LOOKBACK_DAYS)).timestamp())
        
        # Fetch trades from Polymarket Data API for the entire market (condition_id)
        url = "https://data-api.polymarket.com/trades"
        params = {
            'market': condition_id,  # Use condition_id (market) to get all trades for the market
            'limit': 10000  # Get maximum trades for analysis
        }
        
        response = requests.get(url, params=params)
        response.raise_for_status()
        
        trades_data = response.json()
        if not trades_data:
            raise Exception(f"No trades data found for market {condition_id}")
            
        trades_df = pd.DataFrame(trades_data)
        
        if trades_df.empty:
            raise Exception(f"Empty trades data for market {condition_id}")
        
        # Convert timestamps to datetime (API uses 'timestamp' field)
        trades_df['match_time'] = pd.to_datetime(trades_df['timestamp'], unit='s')
        trades_df['price'] = pd.to_numeric(trades_df['price'])
        trades_df['size'] = pd.to_numeric(trades_df['size'])
        
        return trades_df
        
    except Exception as e:
        Logan.error(
            f"Error fetching trades data for market {condition_id}",
            namespace="data_updater.activity_metrics",
            exception=e
        )
        return pd.DataFrame()


def get_market_price_history(token_id: str) -> pd.DataFrame:
    """
    Fetch price history for a given market (condition_id) over the configured lookback period.
    
    Args:
        condition_id: The condition ID (market ID) to fetch price history for
        
    Returns:
        DataFrame with price history including timestamps and prices
    """
    try:
        # Calculate timestamp for lookback period
        end_time = int(datetime.now().timestamp())
        start_time = int((datetime.now() - timedelta(days=TCNF.ACTIVITY_LOOKBACK_DAYS)).timestamp())
        
        # Fetch price history from Polymarket CLOB API
        url = "https://clob.polymarket.com/prices-history"
        params = {
            'market': token_id,
            'startTs': start_time,
            'endTs': end_time,
            'fidelity': 10 # minutes
        }
        
        response = requests.get(url, params=params)
        response.raise_for_status()
        
        price_data = response.json()
        if not price_data or 'history' not in price_data:
            raise Exception(f"No price history found for market {token_id}")
            
        history = price_data['history']
        if not history:
            raise Exception(f"Empty price history for market {token_id}")
        
        # Convert to DataFrame
        price_df = pd.DataFrame(history)
        price_df['timestamp'] = pd.to_datetime(price_df['t'], unit='s')
        price_df['price'] = pd.to_numeric(price_df['p'])
        
        # Sort by timestamp
        price_df = price_df.sort_values('timestamp').reset_index(drop=True)
        
        return price_df[['timestamp', 'price']]
        
    except Exception as e:
        Logan.error(
            f"Error fetching price history for market {token_id}",
            namespace="data_updater.activity_metrics",
            exception=e
        )
        return pd.DataFrame()


def calculate_volume_metrics(trades_df: pd.DataFrame) -> Dict[str, float]:
    """
    Calculate various volume metrics from trades data.
    
    Args:
        trades_df: DataFrame with trade data
        
    Returns:
        Dictionary with volume metrics
    """
    if trades_df.empty:
        return {
            'total_volume': 0.0,
            'volume_usd': 0.0,
            'decay_weighted_volume': 0.0,
            'avg_daily_volume': 0.0
        }
    
    # Calculate total volume (sum of all trade sizes)
    total_volume = trades_df['size'].sum()
    
    # Calculate volume in USD terms (size * price)
    volume_usd = (trades_df['size'] * trades_df['price']).sum()
    
    # Calculate decay weighted volume (more recent trades weighted higher)
    current_time = datetime.now()
    trades_df['hours_ago'] = (current_time - trades_df['match_time']).dt.total_seconds() / 3600
    
    # Use exponential decay with configured half-life
    decay_factor = 0.5 ** (trades_df['hours_ago'] / TCNF.DECAY_HALF_LIFE_HOURS)
    decay_weighted_volume = (trades_df['size'] * decay_factor).sum()
    
    # Average daily volume
    avg_daily_volume = total_volume / max(TCNF.ACTIVITY_LOOKBACK_DAYS, 1)
    
    return {
        'total_volume': round(total_volume, 2),
        'volume_usd': round(volume_usd, 2),
        'decay_weighted_volume': round(decay_weighted_volume, 2),
        'avg_daily_volume': round(avg_daily_volume, 2)
    }




def calculate_trade_frequency(trades_df: pd.DataFrame) -> Dict[str, float]:
    """
    Calculate trade frequency metrics.
    
    Args:
        trades_df: DataFrame with trade data
        
    Returns:
        Dictionary with frequency metrics
    """
    if trades_df.empty:
        return {
            'total_trades': 0,
            'avg_trades_per_day': 0.0,
            'avg_trades_per_hour': 0.0
        }
    
    total_trades = len(trades_df)
    avg_trades_per_day = total_trades / max(TCNF.ACTIVITY_LOOKBACK_DAYS, 1)
    avg_trades_per_hour = total_trades / max(TCNF.ACTIVITY_LOOKBACK_DAYS * 24, 1)
    
    return {
        'total_trades': total_trades,
        'avg_trades_per_day': round(avg_trades_per_day, 2),
        'avg_trades_per_hour': round(avg_trades_per_hour, 4)
    }


# FIRST TODO: Remove data not available in the new API
def calculate_unique_participants(trades_df: pd.DataFrame) -> Dict[str, int]:
    """
    Calculate number of unique traders and transactions.
    
    Args:
        trades_df: DataFrame with trade data
        
    Returns:
        Dictionary with participant metrics
    """
    if trades_df.empty:
        return {
            'unique_makers': 0,
            'unique_takers': 0,
            'unique_traders': 0,
            'unique_transactions': 0
        }
    
    # Count unique wallets (the API uses 'proxyWallet' field)
    unique_wallets = trades_df['proxyWallet'].nunique() if 'proxyWallet' in trades_df.columns else 0
    
    # For this API, we don't have separate maker/taker addresses, just proxyWallet
    unique_makers = 0  # Not available in this API
    unique_takers = 0  # Not available in this API
    unique_traders = unique_wallets
    
    # Unique transactions (using 'transactionHash' field)
    unique_transactions = trades_df['transactionHash'].nunique() if 'transactionHash' in trades_df.columns else len(trades_df)
    
    return {
        'unique_makers': unique_makers,
        'unique_takers': unique_takers,
        'unique_traders': unique_traders,
        'unique_transactions': unique_transactions
    }


def calculate_order_arrival_rate_sensitivity(trades_df: pd.DataFrame, price_df: pd.DataFrame, price_df_token_id: str) -> float:
    """
    Calculate order arrival rate sensitivity (k parameter) from Avellaneda-Stoikov model.
    
    This function implements the exponential decrease of order arrivals as quotes move away
    from the midprice: ln(freq(δ)) ≈ C - kδ
    
    Args:
        trades_df: DataFrame with trade data including timestamps and prices
        price_df: DataFrame with market price history including timestamps and prices
        
    Returns:
        Float: arrival rate sensitivity k parameter
    """
    if trades_df.empty or price_df.empty:
        return 0.0
    
    try:
        # Merge trade data with closest price data
        trade_distances = []
        
        for _, trade in trades_df.iterrows():
            trade_time = trade['match_time']
            
            # Find the closest price timestamp
            time_diff = abs(price_df['timestamp'] - trade_time)
            closest_idx = time_diff.idxmin()
            closest_price = price_df.loc[closest_idx, 'price']
            
            # Calculate half-distance from trade price to midprice
            trade_price = trade['price']
            mid_price = closest_price if trade['asset'] == price_df_token_id else 1 - closest_price
            distance = abs(trade_price - mid_price)
            
            trade_distances.append(distance)
        
        if not trade_distances:
            return 0.0
        
        # Convert to numpy array
        distances = np.array(trade_distances)
        bin_size = TCNF.ARRIVAL_RATE_BIN_SIZE
        
        # Create bins based on distance
        max_distance = distances.max()
        if max_distance == 0:
            return 0.0
        
        bins = np.arange(0, max_distance + bin_size, bin_size)
        bin_indices = np.digitize(distances, bins) - 1
        
        # Count trades in each bin
        bin_counts = np.bincount(bin_indices, minlength=len(bins)-1)
        
        # Filter out bins with zero or very few trades
        valid_indices = np.where(bin_counts >= 2)[0]
        
        if len(valid_indices) < 5:  # Need at least 5 points for meaningful fit
            return 0.0

        # Calculate bin midpoints and ln(frequency)
        x_values = (valid_indices + 0.5) * bin_size
        y_values = np.log(bin_counts[valid_indices])
        
        # Fit linear regression: ln(freq(δ)) = C - k*δ
        slope, intercept, r_value, p_value, std_err = stats.linregress(x_values, y_values)
        
        # k is the negative of the slope
        k_parameter = -slope
        
        return round(k_parameter, 4)
        
    except Exception as e:
        Logan.error(
            "Error calculating order arrival rate sensitivity",
            namespace="data_updater.activity_metrics",
            exception=e
        )
        return 0.0


def calculate_market_activity_metrics(condition_id: str, token_id: str, best_bid: float, best_ask: float) -> Dict[str, float]:
    """
    Calculate all activity metrics for a given market.
    
    Args:
        condition_id: The condition ID (market ID) to analyze
        best_bid: Current best bid price
        best_ask: Current best ask price
        
    Returns:
        Dictionary with all activity metrics
    """
    try:
        # Fetch trades data for the entire market
        trades_df = get_market_trades_data(condition_id)
        
        if trades_df.empty:
            Logan.warn(
                f"No trades data found for market {condition_id}",
                namespace="data_updater.activity_metrics"
            )
            
        # Fetch price history for arrival rate sensitivity calculation
        price_df = get_market_price_history(token_id)
        
        # Calculate all metrics
        volume_metrics = calculate_volume_metrics(trades_df)
        frequency_metrics = calculate_trade_frequency(trades_df)
        participant_metrics = calculate_unique_participants(trades_df)
        arrival_rate_sensitivity = calculate_order_arrival_rate_sensitivity(trades_df, price_df, token_id)
        
        # Combine all metrics
        all_metrics = {
            **volume_metrics,
            **frequency_metrics,
            **participant_metrics,
            'order_arrival_rate_sensitivity': arrival_rate_sensitivity
        }

        return all_metrics
        
    except Exception as e:
        Logan.error(
            f"Error calculating activity metrics for market {condition_id}",
            namespace="data_updater.activity_metrics",
            exception=e
        )
        return {}


def add_activity_metrics_to_market_data(market_row: Dict) -> Dict:
    """
    Add activity metrics to a single market data row.
    This calculates metrics for the entire market (both tokens combined).

    Args:
        market_row: Dictionary containing market data

    Returns:
        Market row enhanced with activity metrics
    """
    condition_id = market_row.get('condition_id')
    token_id = market_row.get('token1') # either token will do. We just use this for the price history
    best_bid = market_row.get('best_bid', 0)
    best_ask = market_row.get('best_ask', 0)

    assert condition_id is not None, "condition_id must be present in market_row"
    assert token_id is not None, "token_id must be present in market_row"

    # Calculate metrics for the entire market over configured lookback period
    activity_metrics = calculate_market_activity_metrics(condition_id, token_id, best_bid, best_ask)
    
    # Add metrics to market row
    enhanced_row = market_row.copy()
    enhanced_row.update(activity_metrics)
    
    return enhanced_row


