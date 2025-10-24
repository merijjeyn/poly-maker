from abc import ABC, abstractmethod


class MarketStrategy(ABC):
    """Abstract base class defining the interface for market making strategies."""
    
    @classmethod
    @abstractmethod
    def get_buy_sell_amount(cls, position, row, force_sell=False) -> tuple[float, float]:
        """Calculate buy and sell amounts based on position and market data."""
        pass

    @classmethod
    @abstractmethod
    def get_order_prices(cls, best_bid, best_ask, mid_price, row, token, tick, force_sell=False) -> tuple[float, float]:
        """Calculate optimal bid and ask prices."""
        pass

    @classmethod
    def apply_safety_guards(cls, bid_price, ask_price, mid_price, tick, best_bid, best_ask, force_sell=False) -> tuple[float, float]:
        # Safety guards
        if mid_price > 0.9 or mid_price < 0.1 or bid_price >= ask_price:
            bid_price = best_bid
            ask_price = best_ask
        
        # I'm a pussy
        if bid_price >= mid_price: 
            bid_price = mid_price - tick
        if ask_price <= mid_price:
            ask_price = mid_price + tick
        
        if force_sell and ask_price > best_ask: 
            ask_price = best_ask
        if force_sell and bid_price >= best_bid: 
            bid_price = best_bid - tick
        
        return bid_price, ask_price