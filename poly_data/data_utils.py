import poly_data.global_state as global_state
from poly_data.utils import get_sheet_df
import time
import poly_data.global_state as global_state
from poly_data.market_selection import filter_selected_markets, calculate_position_size

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
                print(f"ALERT: Skipping update for {asset} because there are trades pending (buy: {global_state.performing.get(buy_key, set())}, sell: {global_state.performing.get(sell_key, set())})")
            else:
                # Also skip shortly after a local trade update to avoid racing API lag
                if asset in global_state.last_trade_update and time.time() - global_state.last_trade_update[asset] < 5:
                    print(f"Skipping update for {asset} because last trade update was less than 5 seconds ago")
                else:
                    try:
                        old_size = position['size']
                    except:
                        old_size = 0

                    if old_size != row['size']:
                        print(f"No trades are pending. Updating position from {old_size} to {row['size']} and avgPrice to {row['avgPrice']} using API")

                    position['size'] = row['size']
    
        global_state.positions[asset] = position


def update_liquidity():
    """Update available cash liquidity for trading"""
    try:
        global_state.available_liquidity = global_state.client.get_usdc_balance()
        print(f"Updated available liquidity: ${global_state.available_liquidity:.2f}")
    except Exception as e:
        print(f"Error updating liquidity: {e}")
        # Keep previous value if update fails

def get_position(token):
    token = str(token)
    if token in global_state.positions:
        return global_state.positions[token]
    else:
        return {'size': 0, 'avgPrice': 0}

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

    print(f"Updated position from {source}, set to ", global_state.positions[token])

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
                            print("Multiple orders found, cancelling")
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
    print("Updated order, set to ", curr)

    

def update_markets():    
    received_df, received_params = get_sheet_df()

    if len(received_df) > 0:
        global_state.df, global_state.params = received_df.copy(), received_params
        
        # Apply custom market filtering logic
        global_state.selected_markets_df = filter_selected_markets(global_state.df)
        
        # Update available liquidity
        update_liquidity()
        
        # Calculate position sizes for each selected market
        global_state.market_position_sizes = {}
        for _, row in global_state.selected_markets_df.iterrows():
            condition_id = str(row['condition_id'])
            position_size_result = calculate_position_size(row, global_state.positions, global_state.available_liquidity)
            global_state.market_position_sizes[condition_id] = position_size_result
    
    # Use selected markets (after filtering) for token tracking and trading setup
    if global_state.selected_markets_df is not None:
        for _, row in global_state.selected_markets_df.iterrows():
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