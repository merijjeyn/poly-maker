"""
Configuration settings for the Poly-Maker trading system.

This module contains all constants used throughout the application,
organized into logical groups for different system components.
"""

class TradingConfig:
    """Configuration constants for trading logic and operations."""
    
    # Order pricing and execution thresholds
    SELL_ONLY_THRESHOLD = 0.8
    MIN_PRICE_LIMIT = 0.1
    MAX_PRICE_LIMIT = 0.9
    PRICE_PRECISION_LIMIT = 0.99  # Box sum guard threshold
    ORDER_EXPIRATION_SEC = 900
    
    # Order cancellation thresholds
    # TODO: I don't like this. It doesn't make sense for markets with lower ticks.
    BUY_PRICE_DIFF_THRESHOLD = 0.001  # Cancel if price diff > 0.1 cents
    SELL_PRICE_DIFF_THRESHOLD = 0.001  # Cancel if price diff > 0.1 cents
    SIZE_DIFF_PERCENTAGE = 0.1  # Cancel if size diff > 10%
    
    # Position merging and size limits
    MIN_MERGE_SIZE = 20  # From CONSTANTS.py
    
    # Market selection and investment parameters
    INVESTMENT_CEILING = 2000
    MAX_POSITION_MULT = 3
    BUDGET_MULT = 2
    MARKET_COUNT = 20
    
    # Risk management thresholds
    MAX_VOLATILITY_SUM = 14.0
    MIN_ATTRACTIVENESS_SCORE = 0.0
    MARKET_IMBALANCE_CALC_PCT = 0.3 # percentage of midpoint to include in imbalance calculation
    MARKET_IMBALANCE_CALC_LEVELS = 5 # number of price levels to include in imbalance calculation
    MAX_MARKET_ORDER_IMBALANCE = 0.6 # absolute value. 1, -1 means completely imbalanced. 0 means completely balanced.
    
    # Activity metrics calculation parameters
    ACTIVITY_LOOKBACK_DAYS = 7  # Number of days to look back for activity metrics
    DECAY_HALF_LIFE_HOURS = 24  # Half-life for decay weighting (hours)
    
    # Activity and volume filtering thresholds
    MIN_TOTAL_VOLUME = 1000.0  # Minimum total trading volume over lookback period
    MIN_VOLUME_USD = 0  # Minimum USD volume over lookback period
    MIN_DECAY_WEIGHTED_VOLUME = 400.0  # Minimum decay-weighted volume (recent activity emphasized)
    MIN_AVG_TRADES_PER_DAY = 6.0  # Minimum average trades per day
    MIN_UNIQUE_TRADERS = 5  # Minimum number of unique traders

    # Market strategy parameters
    RISK_AVERSION = 0.4
    TIME_TO_HORIZON_HOURS = 24
    ARRIVAL_RATE_BIN_SIZE = 0.01
    MIN_ARRIVAL_RATE_SENSITIVITY = 1.0
    MAX_ARRIVAL_RATE_SENSITIVITY = 80.0
    REWARD_SKEW_FACTOR = 0.1

    


class MarketProcessConfig:
    """Configuration constants for market data processing and updates."""
    
    # Update intervals and timing
    POSITION_UPDATE_INTERVAL = 5  # seconds
    MARKET_UPDATE_INTERVAL = 30  # seconds
    STALE_TRADE_TIMEOUT = 15  # seconds to wait before removing stale trades
    
    # Calculated cycle count (how many position update cycles = 1 market update cycle)
    @property
    def MARKET_UPDATE_CYCLE_COUNT(self):
        import math
        return math.ceil(self.MARKET_UPDATE_INTERVAL / self.POSITION_UPDATE_INTERVAL)
    
    # WebSocket and API configuration
    WEBSOCKET_PING_INTERVAL = 5
    HTTP_TIMEOUT = 30  # seconds for HTTP requests
    
    # Data processing constants
    TICK_SIZE_CALCULATION_FACTOR = 100  # For price calculations
    
    # Market depth calculation
    MARKET_DEPTH_EPS = 1e-6  # Small value to avoid division by zero
    DEFAULT_IN_GAME_MULTIPLIER = 1.0
    DEFAULT_ALPHA = 0.1
    
    # Price range calculations
    TICK_SIZE_OFFSET = 1  # For rounding start point in generate_numbers
    PRICE_CALCULATION_PRECISION = 100  # For 1/price * 100 calculations


# Singleton instances for easy import
TCNF = TradingConfig()
MCNF = MarketProcessConfig()