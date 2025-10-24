import time
from typing import Dict
from dataclasses import dataclass

from logan import Logan

# Time in seconds after which an order in flight is considered stale
ORDER_IN_FLIGHT_TIMEOUT = 120  # 2 minutes

@dataclass
class OrderInFlight:
    """Represents an order that has been submitted but not yet confirmed."""
    side: str  # 'buy' or 'sell'
    price: float
    size: float
    timestamp: float


# Global tracking of orders that have been submitted but not yet confirmed
# Structure: {market: {orderId: OrderInFlight}}
_orders_in_flight: Dict[str, Dict[str, OrderInFlight]] = {}


def get_orders_in_flight(market: str) -> Dict[str, OrderInFlight]:
    """
    Get all orders in flight for a given token.
    Automatically filters out stale orders older than ORDER_IN_FLIGHT_TIMEOUT.

    Args:
        market: The market to get orders for

    Returns:
        Dictionary of {orderId: OrderInFlight} for the token
    """
    if market not in _orders_in_flight:
        return {}

    current_time = time.time()
    orders = _orders_in_flight[market]

    # Filter out stale orders and clean them up
    stale_order_ids = [
        order_id for order_id, order_data in orders.items()
        if current_time - order_data.timestamp > ORDER_IN_FLIGHT_TIMEOUT
    ]

    for order_id in stale_order_ids:
        del orders[order_id]

    # Clean up empty token entries
    if not orders:
        del _orders_in_flight[market]
        return {}

    return orders.copy()


def set_order_in_flight(market: str, order_id: str, side: str, price: float, size: float):
    """
    Add or update an order in flight.

    Args:
        market: The market to set the order for
        order_id: The unique order ID
        side: 'buy' or 'sell'
        price: Order price
        size: Order size
    """
    if market not in _orders_in_flight:
        _orders_in_flight[market] = {}

    _orders_in_flight[market][order_id] = OrderInFlight(
        side=side,
        price=price,
        size=size,
        timestamp=time.time()
    )


def clear_order_in_flight(order_id: str):
    """
    Remove an order from in-flight tracking by order ID.
    Searches across all markets.

    Args:
        order_id: The order ID to remove
    """
    for market in list(_orders_in_flight.keys()):
        if order_id in _orders_in_flight[market]:
            del _orders_in_flight[market][order_id]
            # Clean up empty market entries
            if not _orders_in_flight[market]:
                del _orders_in_flight[market]
            break
