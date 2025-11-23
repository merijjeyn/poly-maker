import trading_bot.global_state as global_state
import time
from logan import Logan

# Note: is accidently removing position bug fixed? 
def update_positions(avgOnly=False):
    pos_df = global_state.client.get_all_positions()

    for idx, row in pos_df.iterrows():
        asset = str(row['asset'])

        if asset in  global_state.positions:
            position = global_state.positions[asset].copy()
        else:
            position = {'size': 0, 'avgPrice': 0.0}

        position['avgPrice'] = row['avgPrice']

        if not avgOnly:
            position['size'] = row['size']
        else:
            # Only update size if there are no pending trades on either side
            buy_key = f"{asset}_buy"
            sell_key = f"{asset}_sell"

            buy_pending = isinstance(global_state.performing.get(buy_key, set()), set) and len(global_state.performing.get(buy_key, set())) > 0
            sell_pending = isinstance(global_state.performing.get(sell_key, set()), set) and len(global_state.performing.get(sell_key, set())) > 0

            if buy_pending or sell_pending:
                Logan.warn(
                    f"ALERT: Skipping update for {asset} because there are trades pending (buy: {global_state.performing.get(buy_key, set())}, sell: {global_state.performing.get(sell_key, set())})",
                    namespace="poly_data.data_utils"
                )
            else:
                # Also skip shortly after a local trade update to avoid racing API lag
                if asset in global_state.last_trade_update and time.time() - global_state.last_trade_update[asset] < 5:
                    Logan.info(
                        f"Skipping update for {asset} because last trade update was less than 5 seconds ago",
                        namespace="poly_data.data_utils"
                    )
                else:
                    try:
                        old_size = position['size']
                    except Exception as e:
                        Logan.error(
                            f"Error getting old position size for {asset}",
                            namespace="poly_data.data_utils",
                            exception=e
                        )
                        old_size = 0

                    if old_size != row['size']:
                        Logan.info(
                            f"No trades are pending. Updating position from {old_size} to {row['size']} and avgPrice to {row['avgPrice']} using API",
                            namespace="poly_data.data_utils"
                        )

                    position['size'] = row['size']
    
        global_state.positions[asset] = position


def update_liquidity():
    """Update available cash liquidity for trading"""
    try:
        global_state.available_liquidity = global_state.client.get_usdc_balance()
    except Exception as e:
        Logan.error(
            "Error updating liquidity",
            namespace="poly_data.data_utils",
            exception=e
        )
        # Keep previous value if update fails

def get_total_balance() -> float:
    """Calculate total balance as available liquidity plus invested collateral.

    Uses in-memory state:
    - `global_state.available_liquidity` for current USDC balance
    - `global_state.positions` valued at average entry price (size * avgPrice)

    Returns:
        float | None: Total balance if computable, otherwise None.
    """
    try:
        liquidity = float(global_state.available_liquidity) if global_state.available_liquidity is not None else 0.0

        positions_value = 0.0
        for _, position in getattr(global_state, 'positions', {}).items():
            size = float(position.get('size', 0) or 0)
            avg_price = float(position.get('avgPrice', 0) or 0)
            if size > 0 and avg_price > 0:
                positions_value += size * avg_price

        total = liquidity + positions_value
        return total
    except Exception as e:
        Logan.error(
            "Error calculating total balance",
            namespace="poly_data.data_utils",
            exception=e
        )
        return 0.0

def get_position(token):
    token = str(token)
    if token in global_state.positions:
        return global_state.positions[token]
    else:
        return {'size': 0, 'avgPrice': 0.0}

def get_readable_from_condition_id(condition_id) -> str:
    if global_state.df is not None and len(global_state.df) > 0:
        matching_market = global_state.df[global_state.df['condition_id'] == str(condition_id)]
        if len(matching_market) > 0:
            return matching_market.iloc[0]['question']
    Logan.error(
        f"No matching market found for condition ID {condition_id}, df length: {len(global_state.df)}",
    )
    return "Unknown"
    
def set_position(token, side, size, price, source='websocket'):
    token = str(token)
    size = float(size)
    price = float(price)

    global_state.last_trade_update[token] = time.time()
    
    if side.lower() == 'sell':
        size *= -1

    if token in global_state.positions:
        
        prev_price = global_state.positions[token]['avgPrice']
        prev_size = global_state.positions[token]['size']

        if size > 0:
            if prev_size == 0:
                # Starting a new position
                avgPrice_new = price
            else:
                # Buying more; update average price
                avgPrice_new = (prev_price * prev_size + price * size) / (prev_size + size)
        elif size < 0:
            # Selling; average price remains the same
            avgPrice_new = prev_price
        else:
            # No change in position
            avgPrice_new = prev_price


        global_state.positions[token]['size'] += size
        global_state.positions[token]['avgPrice'] = avgPrice_new
    else:
        global_state.positions[token] = {'size': size, 'avgPrice': price}

    Logan.info(
        f"Updated position from {source}, set to {global_state.positions[token]}",
        namespace="poly_data.data_utils"
    )

def clear_all_orders():
    """Clear all existing open orders on startup"""
    try:
        all_orders = global_state.client.get_all_orders()

        if len(all_orders) > 0:
            Logan.info(f"Clearing {len(all_orders)} existing orders on startup", namespace="poly_data.data_utils")

            # Cancel orders by asset to be efficient
            assets_to_cancel = set(all_orders['asset_id'].astype(str))
            for asset_id in assets_to_cancel:
                try:
                    global_state.client.cancel_all_asset(asset_id)
                    Logan.info(f"Cleared orders for asset {asset_id}", namespace="poly_data.data_utils")
                except Exception as e:
                    Logan.error(f"Error clearing orders for asset {asset_id}", namespace="poly_data.data_utils", exception=e)
        else:
            Logan.info("No existing orders to clear", namespace="poly_data.data_utils")

    except Exception as e:
        Logan.error("Error clearing all orders", namespace="poly_data.data_utils", exception=e)

def update_orders():
    all_orders = global_state.client.get_all_orders()

    orders = {}

    if len(all_orders) > 0:
            for token in all_orders['asset_id'].unique():
                
                if token not in orders:
                    orders[str(token)] = {'buy': {'price': 0, 'size': 0}, 'sell': {'price': 0, 'size': 0}}

                curr_orders = all_orders[all_orders['asset_id'] == str(token)]
                
                if len(curr_orders) > 0:
                    sel_orders = {}
                    sel_orders['buy'] = curr_orders[curr_orders['side'] == 'BUY']
                    sel_orders['sell'] = curr_orders[curr_orders['side'] == 'SELL']

                    for type in ['buy', 'sell']:
                        curr = sel_orders[type]

                        if len(curr) > 1:
                            Logan.warn(
                                "Multiple orders found, cancelling",
                                namespace="poly_data.data_utils"
                            )
                            global_state.client.cancel_all_asset(token)
                            orders[str(token)] = {'buy': {'price': 0, 'size': 0}, 'sell': {'price': 0, 'size': 0}}
                        elif len(curr) == 1:
                            orders[str(token)][type]['price'] = float(curr.iloc[0]['price'])
                            orders[str(token)][type]['size'] = float(curr.iloc[0]['original_size'] - curr.iloc[0]['size_matched'])

    global_state.orders = orders

def get_order(token) -> dict[str, dict[str, float]]:
    token = str(token)
    if token in global_state.orders:

        if 'buy' not in global_state.orders[token]:
            global_state.orders[token]['buy'] = {'price': 0.0, 'size': 0.0}

        if 'sell' not in global_state.orders[token]:
            global_state.orders[token]['sell'] = {'price': 0.0, 'size': 0.0}

        return global_state.orders[token]
    else:
        return {'buy': {'price': 0.0, 'size': 0.0}, 'sell': {'price': 0.0, 'size': 0.0}}
    
def set_order(token, side, size, price):
    curr = {}
    curr = {side: {'price': 0.0, 'size': 0.0}}

    curr[side]['size'] = float(size)
    curr[side]['price'] = float(price)

    global_state.orders[str(token)] = curr
    Logan.info(
        f"Updated order, set to {curr}",
        namespace="poly_data.data_utils"
    )

    
