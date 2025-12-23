from sortedcontainers import SortedDict
from typing import Optional, Dict
from logan import Logan
import trading_bot.global_state as global_state


class OrderBook:
    """Manages order book and user orders for a single token."""

    def __init__(self, token: str, reverse_token: Optional[str]):
        self.token = str(token)
        self.reverse_token = str(reverse_token) if reverse_token else None

        # Initialize data structures
        self.bids = SortedDict()  # price -> size
        self.asks = SortedDict()  # price -> size
        self.orders = {
            'buy': {'price': 0.0, 'size': 0.0},
            'sell': {'price': 0.0, 'size': 0.0}
        }

    def process_book_data(self, json_data: dict):
        """Process full order book snapshot from WebSocket"""
        self.bids.clear()
        self.asks.clear()

        for entry in json_data['bids']:
            price = round(float(entry['price']), 2)
            size = float(entry['size'])
            self.bids[price] = size

        for entry in json_data['asks']:
            price = round(float(entry['price']), 2)
            size = float(entry['size'])
            self.asks[price] = size

        # Sync reverse token
        self._sync_reverse_token()

    def _sync_reverse_token(self):
        """Sync the reverse token's order book (NO/YES mirror)"""
        if not self.reverse_token:
            return

        # Import here to avoid circular import
        reverse_ob = OrderBooks._get_or_create(self.reverse_token, self.token)
        reverse_ob.bids.clear()
        reverse_ob.asks.clear()

        # Reverse asks become bids (at 1-price)
        for price, size in self.asks.items():
            rev_price = round(float(1 - price), 2)
            reverse_ob.bids[rev_price] = size

        # Reverse bids become asks (at 1-price) 
        for price, size in self.bids.items():
            rev_price = round(float(1 - price), 2)
            reverse_ob.asks[rev_price] = size

    def update_book_data_for_order_event(self, book_side: str, price: float, delta: float):
        """
        Update order book based on order event.

        Args:
            book_side: 'bids' or 'asks'
            price: Order price
            delta: Change in size (positive for new orders, negative for cancellations)
        """
        price = round(price, 2)
        delta = round(delta, 2)

        # Update order book
        book = self.bids if book_side == 'bids' else self.asks
        current_size = book.get(price, 0)
        new_size = max(current_size + delta, 0)

        if new_size == 0:
            book.pop(price, None)
        else:
            book[price] = new_size

        # Sync reverse token
        self._sync_reverse_token()

        reverse_token = self.reverse_token
        reverse_book = OrderBooks.get(reverse_token) if reverse_token else None
        if reverse_book:
            Logan.debug(
                f"updated book data for token {self.token}: bids={dict(self.bids)}, asks={dict(self.asks)}, "
                f"reverse book data for token {reverse_token}: bids={dict(reverse_book.bids)}, asks={dict(reverse_book.asks)}"
            )

    def set_order(self, side: str, size: float, price: float):
        """
        Set user's own order.

        Args:
            side: 'buy' or 'sell'
            size: Order size
            price: Order price
        """
        price = round(price, 2)
        self.orders[side] = {'price': price, 'size': size}

        # Also update reverse token's orders
        if self.reverse_token:
            reverse_ob = OrderBooks._get_or_create(self.reverse_token, self.token)
            rev_side = 'buy' if side == 'sell' else 'sell'
            reverse_ob.orders[rev_side] = {'price': price, 'size': size}

    def get_order(self, side: str) -> Dict[str, float]:
        """Get user's own order for a side"""
        if side not in self.orders:
            return {'price': 0.0, 'size': 0.0}
        return self.orders[side]

    def get_all_orders(self) -> Dict[str, Dict[str, float]]:
        """Get all user's orders (buy and sell)"""
        return {
            'buy': self.get_order('buy'),
            'sell': self.get_order('sell')
        }


class OrderBooks:
    """Static class that manages order books for all tokens."""

    # Class-level state
    _order_books: Dict[str, OrderBook] = {}

    @classmethod
    def _get_or_create(cls, token: str, reverse_token: Optional[str] = None) -> OrderBook:
        """Internal method to get or create an order book"""
        token = str(token)
        if token not in cls._order_books:
            if reverse_token is None:
                reverse_token = global_state.REVERSE_TOKENS.get(token, None)
            cls._order_books[token] = OrderBook(token, reverse_token)
        return cls._order_books[token]

    @classmethod
    def get(cls, token: str) -> OrderBook:
        """Get order book for a token"""
        token = str(token)
        reverse_token = global_state.REVERSE_TOKENS.get(token, None)
        return cls._get_or_create(token, reverse_token)

    @classmethod
    def get_order_book_exclude_self(cls, token: str) -> dict:
        """
        Get the order book for a token with the user's own orders excluded.

        This returns a copy of the order book where the user's own buy orders
        are subtracted from bids and sell orders are subtracted from asks.

        Args:
            token: The token ID to get the order book for

        Returns:
            Dict with 'bids' and 'asks' SortedDicts, excluding self orders
        """
        token = str(token)
        order_book = cls.get(token)

        # Create copies of the order book
        bids_copy = SortedDict(order_book.bids)
        asks_copy = SortedDict(order_book.asks)

        # Get user's orders for this token
        buy_order = order_book.get_order('buy')
        sell_order = order_book.get_order('sell')

        # Subtract buy orders from bids
        if buy_order and buy_order.get('size', 0) > 0:
            buy_price = round(float(buy_order.get('price', 0)), 2)
            if buy_price in bids_copy:
                new_size = bids_copy[buy_price] - buy_order['size']
                if new_size <= 0:
                    del bids_copy[buy_price]
                else:
                    bids_copy[buy_price] = new_size

        # Subtract sell orders from asks
        if sell_order and sell_order.get('size', 0) > 0:
            sell_price = round(float(sell_order.get('price', 0)), 2)
            if sell_price in asks_copy:
                new_size = asks_copy[sell_price] - sell_order['size']
                if new_size <= 0:
                    del asks_copy[sell_price]
                else:
                    asks_copy[sell_price] = new_size

        return {'bids': bids_copy, 'asks': asks_copy}
