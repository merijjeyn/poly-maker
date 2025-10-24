import pandas as pd
import trading_bot.global_state as global_state
from google_utils import get_sheet_df
import time
import trading_bot.global_state as global_state
from trading_bot.market_selection import calculate_position_sizes, filter_selected_markets
from logan import Logan

# Note: is accidently removing position bug fixed? 
def update_positions(avgOnly=False):
    pos_df = global_state.client.get_all_positions()

    for idx, row in pos_df.iterrows():
        asset = str(row['asset'])

        if asset in  global_state.positions:
            position = global_state.positions[asset].copy()
        else:
            position = {'size': 0, 'avgPrice': 0}

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
            f"Error updating liquidity",
            namespace="poly_data.data_utils",
            exception=e
        )
        # Keep previous value if update fails

def get_total_balance():
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
        global_state.total_balance = total
        return total
    except Exception as e:
        Logan.error(
            f"Error calculating total balance",
            namespace="poly_data.data_utils",
            exception=e
        )
        return None

def get_position(token):
    token = str(token)
    if token in global_state.positions:
        return global_state.positions[token]
    else:
        return {'size': 0, 'avgPrice': 0}

def get_readable_from_condition_id(condition_id) -> str:
    if global_state.df is not None and len(global_state.df) > 0:
        matching_market = global_state.df[global_state.df['condition_id'] == str(condition_id)]
        if len(matching_market) > 0:
            return matching_market['question'].iloc[0]
    Logan.error(
        f"No matching market found for condition ID {condition_id}, df length: {len(global_state.df)}",
    )
    return "Unknown"

def get_readable_from_token_id(token_id) -> str:
    if global_state.df is not None and len(global_state.df) > 0:
        matching_market = global_state.df[
            (global_state.df['token1'] == token_id) | 
            (global_state.df['token2'] == token_id)
        ]
        if len(matching_market) > 0:
            return matching_market['question'].iloc[0]
    Logan.error(
        f"No matching market found for token ID {token_id}, df length: {len(global_state.df)}",
        namespace="poly_data.data_utils"
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
        Logan.error(f"Error clearing all orders", namespace="poly_data.data_utils", exception=e)

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

def get_order(token):
    token = str(token)
    if token in global_state.orders:

        if 'buy' not in global_state.orders[token]:
            global_state.orders[token]['buy'] = {'price': 0, 'size': 0}

        if 'sell' not in global_state.orders[token]:
            global_state.orders[token]['sell'] = {'price': 0, 'size': 0}

        return global_state.orders[token]
    else:
        return {'buy': {'price': 0, 'size': 0}, 'sell': {'price': 0, 'size': 0}}
    
def set_order(token, side, size, price):
    curr = {}
    curr = {side: {'price': 0, 'size': 0}}

    curr[side]['size'] = float(size)
    curr[side]['price'] = float(price)

    global_state.orders[str(token)] = curr
    Logan.info(
        f"Updated order, set to {curr}",
        namespace="poly_data.data_utils"
    )

    

def update_markets_with_positions():
    """Create dataframe of markets where we currently have positions"""
    if global_state.positions:
        position_tokens = set()
        for token, position in global_state.positions.items():
            if position['size'] > 0:
                position_tokens.add(str(token))
        
        if position_tokens:
            # Find markets that contain any of our position tokens
            global_state.markets_with_positions = global_state.df[
                global_state.df['token1'].astype(str).isin(position_tokens) | 
                global_state.df['token2'].astype(str).isin(position_tokens)
            ].copy()
        else:
            global_state.markets_with_positions = global_state.df.iloc[0:0].copy()  # Empty dataframe with same structure
    else:
        global_state.markets_with_positions = global_state.df.iloc[0:0].copy()  # Empty dataframe with same structure

def update_markets():    
    received_df, received_params = get_sheet_df()

    if len(received_df) > 0:
        global_state.df, global_state.params = received_df.copy(), received_params
        
        # Apply custom market filtering logic
        global_state.selected_markets_df = filter_selected_markets(global_state.df)
        
        # Update markets with positions
        update_markets_with_positions()
        
        # Update available liquidity
        update_liquidity()
        
        calculate_position_sizes()
    
    combined_markets = global_state.get_active_markets()  
    if combined_markets is not None:
        for _, row in combined_markets.iterrows():
            for col in ['token1', 'token2']:
                row[col] = str(row[col])

            if row['token1'] not in global_state.all_tokens:
                global_state.all_tokens.append(row['token1'])

            if row['token1'] not in global_state.REVERSE_TOKENS:
                global_state.REVERSE_TOKENS[row['token1']] = row['token2']

            if row['token2'] not in global_state.REVERSE_TOKENS:
                global_state.REVERSE_TOKENS[row['token2']] = row['token1']

            for col2 in [f"{row['token1']}_buy", f"{row['token1']}_sell", f"{row['token2']}_buy", f"{row['token2']}_sell"]:
                if col2 not in global_state.performing:
                    global_state.performing[col2] = set() 