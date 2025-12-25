from collections import defaultdict, deque
import time
import numpy as np
import trading_bot.global_state as global_state


class VolatilityTracker:
    def __init__(self, window_hours=4):
        self.window_seconds = window_hours * 60 * 60
        self.start_time = time.time()
        # token -> deque of (timestamp, price)
        self.price_history: dict[str, deque] = defaultdict(deque)

    def record_price(self, token: str, price: float, timestamp: float):
        """Record a trade price for a token and its reverse token."""
        self.price_history[token].append((timestamp, price))
        self._prune_old(token)

        # Also record for reverse token (with inverse price)
        if token in global_state.REVERSE_TOKENS:
            reverse_token = global_state.REVERSE_TOKENS[token]
            reverse_price = 1.0 - price
            self.price_history[reverse_token].append((timestamp, reverse_price))
            self._prune_old(reverse_token)

    def _prune_old(self, token: str):
        """Remove entries older than the window."""
        cutoff = time.time() - self.window_seconds
        while self.price_history[token] and self.price_history[token][0][0] < cutoff:
            self.price_history[token].popleft()

    def _calculate_volatility_for_window(self, token: str, hours: float) -> float | None:
        """
        Calculate annualized volatility for the given window.
        Returns None if we haven't been tracking long enough.
        """
        # Check if tracker has been running long enough for this window
        elapsed_since_start = time.time() - self.start_time
        if elapsed_since_start < hours * 60 * 60:
            return None 

        self._prune_old(token)
        history = self.price_history[token]

        window_start = time.time() - (hours * 60 * 60)

        # Get prices in window
        prices = [p for t, p in history if t >= window_start]

        # Log returns (same as find_markets.py)
        log_returns = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0 and prices[i] > 0:
                log_returns.append(np.log(prices[i] / prices[i-1]))

        if len(log_returns) < 2:
            return 0

        # Annualized volatility (same formula as find_markets.py)
        volatility = np.std(log_returns)
        return round(volatility * np.sqrt(60 * 24 * 252), 2)

    def get_volatility_for_market(self, token: str, row: dict) -> float:
        """
        Returns volatility_sum = 1h + 3h + 24h + 7d
        Uses in-memory for 1h/3h if data goes back far enough, else falls back to row.
        24h and 7d always come from row (we only keep 3h in memory).
        """
        vol_1h = self._calculate_volatility_for_window(token, 1)
        vol_3h = self._calculate_volatility_for_window(token, 3)

        row_1h = row.get('1_hour', 0)
        row_3h = row.get('3_hour', 0)
        row_24h = row.get('24_hour', 0)
        row_7d = row.get('7_day', 0)

        final_1h = vol_1h if vol_1h is not None else row_1h
        final_3h = vol_3h if vol_3h is not None else row_3h

        return final_1h + final_3h + row_24h + row_7d

    def get_data_age_hours(self, token: str) -> float | None:
        """Returns how many hours of data we have for this token, or None if no data."""
        if token not in self.price_history or len(self.price_history[token]) == 0:
            return None

        oldest = self.price_history[token][0][0]
        return (time.time() - oldest) / 3600


# Singleton instance
volatility_tracker = VolatilityTracker()
