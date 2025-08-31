import gc                       # Garbage collection
import os                       # Operating system interface
import json                     # JSON handling
import asyncio                  # Asynchronous I/O
import pandas as pd             # Data analysis library
import math                     # Mathematical functions
from logan import Logan         # Logging

import poly_data.global_state as global_state
import poly_data.CONSTANTS as CONSTANTS

# Import utility functions for trading
from poly_data.trading_utils import get_best_bid_ask_deets, get_order_prices, get_buy_sell_amount, round_down, round_up
from poly_data.data_utils import get_position, get_order, get_question_by_condition_id, get_total_balance, set_position
from poly_data.market_selection import get_enhanced_market_row

SELL_ONLY_THRESHOLD = 0.6

# Create directory for storing position risk information
if not os.path.exists('positions/'):
    os.makedirs('positions/')

def send_buy_order(order):
    """
    Create a BUY order for a specific token.
    
    This function:
    1. Cancels any existing orders for the token
    2. Checks if the order price is within acceptable range
    3. Creates a new buy order if conditions are met
    
    Args:
        order (dict): Order details including token, price, size, and market parameters
    """
    client = global_state.client

    # Only cancel existing orders if we need to make significant changes
    existing_buy_size = order['orders']['buy']['size']
    existing_buy_price = order['orders']['buy']['price']
    
    # Cancel orders if price changed significantly or size needs major adjustment
    price_diff = abs(existing_buy_price - order['price']) if existing_buy_price > 0 else float('inf')
    size_diff = abs(existing_buy_size - order['size']) if existing_buy_size > 0 else float('inf')
    
    should_cancel = (
        price_diff > 0.002 or  # Cancel if price diff > 0.2 cents
        size_diff > order['size'] * 0.1 or  # Cancel if size diff > 10%
        existing_buy_size == 0  # Cancel if no existing buy order
    )
    
    if should_cancel and (existing_buy_size > 0 or order['orders']['sell']['size'] > 0):
        Logan.info(f"Cancelling buy orders - price diff: {price_diff:.4f}, size diff: {size_diff:.1f}", namespace="trading")
        client.cancel_all_asset(order['token'])
    elif not should_cancel:
        Logan.info(f"Keeping existing buy orders - minor changes: price diff: {price_diff:.4f}, size diff: {size_diff:.1f}", namespace="trading")
        return  # Don't place new order if existing one is fine

    # Calculate minimum acceptable price based on market spread
    incentive_start = order['mid_price'] - order['max_spread']/100

    trade = True

    # Don't place orders that are below incentive threshold
    if order['price'] < incentive_start:
        trade = False

    if trade:
        # Only place orders with prices between 0.1 and 0.9 to avoid extreme positions
        if order['price'] >= 0.1 and order['price'] < 0.9:
            client.create_order(
                order['token'], 
                'BUY', 
                order['price'], 
                order['size'], 
                True if order['neg_risk'] == 'TRUE' else False
            )
        else:
            Logan.warn("Not creating buy order because its outside acceptable price range (0.1-0.9)", namespace="trading")
    else:
        Logan.info(f'Not creating new order because order price of {order["price"]} is less than incentive start price of {incentive_start}. Mid price is {order["mid_price"]}', namespace="trading")


def send_sell_order(order):
    """
    Create a SELL order for a specific token.
    
    This function:
    1. Cancels any existing orders for the token
    2. Creates a new sell order with the specified parameters
    
    Args:
        order (dict): Order details including token, price, size, and market parameters
    """
    client = global_state.client

    # Only cancel existing orders if we need to make significant changes
    existing_sell_size = order['orders']['sell']['size']
    existing_sell_price = order['orders']['sell']['price']
    
    # Cancel orders if price changed significantly or size needs major adjustment
    price_diff = abs(existing_sell_price - order['price']) if existing_sell_price > 0 else float('inf')
    size_diff = abs(existing_sell_size - order['size']) if existing_sell_size > 0 else float('inf')
    
    should_cancel = (
        price_diff > 0.001 or  # Cancel if price diff > 0.1 cents
        size_diff > order['size'] * 0.1 or  # Cancel if size diff > 10%
        existing_sell_size == 0  # Cancel if no existing sell order
    )
    
    if should_cancel and (existing_sell_size > 0 or order['orders']['buy']['size'] > 0):
        Logan.info(f"Cancelling sell orders - price diff: {price_diff:.4f}, size diff: {size_diff:.1f}", namespace="trading")
        client.cancel_all_asset(order['token'])
    elif not should_cancel:
        Logan.info(f"Keeping existing sell orders - minor changes: price diff: {price_diff:.4f}, size diff: {size_diff:.1f}", namespace="trading")
        return  # Don't place new order if existing one is fine

    Logan.info(f'Creating new sell order for {order["size"]} at {order["price"]}', namespace="trading")
    client.create_order(
        order['token'], 
        'SELL', 
        order['price'], 
        order['size'], 
        True if order['neg_risk'] == 'TRUE' else False
    )

# Dictionary to store locks for each market to prevent concurrent trading on the same market
market_locks = {}

async def perform_trade(market):
    """
    Main trading function that handles market making for a specific market.
    
    This function:
    1. Merges positions when possible to free up capital
    2. Analyzes the market to determine optimal bid/ask prices
    3. Manages buy and sell orders based on position size and market conditions
    4. Implements risk management with stop-loss and take-profit logic
    
    Args:
        market (str): The market ID to trade on
    """
    # Create a lock for this market if it doesn't exist
    if market not in market_locks:
        market_locks[market] = asyncio.Lock()

    # Use lock to prevent concurrent trading on the same market
    async with market_locks[market]:
        try:
            client = global_state.client
            # Get market details from the configuration with enhanced position sizing
            row = get_enhanced_market_row(market)

            # Skip trading if market is not in selected markets (filtered out)
            if row is None:
                Logan.warn(f"Market {market} not found in active markets, skipping", namespace="trading")
                return
            
            # Check if market is in positions but not in selected markets (sell-only mode to free up capital)
            sell_only = False
            if hasattr(global_state, 'markets_with_positions') and hasattr(global_state, 'selected_markets_df'):
                in_positions = market in global_state.markets_with_positions['condition_id'].values if global_state.markets_with_positions is not None else False
                in_selected = market in global_state.selected_markets_df['condition_id'].values if global_state.selected_markets_df is not None else False
                sell_only = in_positions and not in_selected      
            
            # Also sell if we have used most of our budget
            total_balance = get_total_balance()
            if global_state.available_liquidity < total_balance * (1 - SELL_ONLY_THRESHOLD):
                sell_only = True
            
            # Determine decimal precision from tick size
            round_length = len(str(row['tick_size']).split(".")[1])

            # Get trading parameters for this market type
            # params = global_state.params[row['param_type']]
            params = global_state.params['mid'] # hardcode for now
            
            # Create a list with both outcomes for the market
            deets = [
                {'name': 'token1', 'token': row['token1'], 'answer': row['answer1']}, 
                {'name': 'token2', 'token': row['token2'], 'answer': row['answer2']}
            ]

            # Get current positions for both outcomes
            pos_1 = get_position(row['token1'])['size']
            pos_2 = get_position(row['token2'])['size']

            # ------- POSITION MERGING LOGIC -------
            # Calculate if we have opposing positions that can be merged
            amount_to_merge = min(pos_1, pos_2)
            
            # TODO: Do we want to merge whenever available, or sometimes push for better prices? 
            # Only merge if positions are above minimum threshold
            if float(amount_to_merge) > CONSTANTS.MIN_MERGE_SIZE:
                # Get exact position sizes from blockchain for merging
                pos_1_raw = client.get_position(row['token1'])[0]
                pos_2_raw = client.get_position(row['token2'])[0]
                amount_to_merge_raw = min(pos_1_raw, pos_2_raw)

                Logan.info(f"Position 1 is of size {pos_1_raw} and Position 2 is of size {pos_2_raw}. Merging positions", namespace="trading")
                # Execute the merge operation
                Logan.info(f"Merging {amount_to_merge_raw} of {row['token1']} and {row['token2']}", namespace="trading")

                try:
                    client.merge_positions(amount_to_merge_raw, market, row['neg_risk'] == 'TRUE')
                except Exception as e:
                    Logan.error(f"Error merging {amount_to_merge_raw} positions for market \"{get_question_by_condition_id(market)}\": {e}", namespace="trading", exception=e)
                
                # TODO: for now, let it get updated by the background task
                # Update our local position tracking
                # scaled = amount_to_merge / 10**6
                # set_position(row['token1'], 'SELL', scaled, 0, 'merge')
                # set_position(row['token2'], 'SELL', scaled, 0, 'merge')
                
            # ------- TRADING LOGIC FOR EACH OUTCOME -------
            # Loop through both outcomes in the market (YES and NO)
            for detail in deets:
                token = int(detail['token'])
                
                # Get current orders for this token
                orders = get_order(token)

                # Get market depth and price information
                deets = get_best_bid_ask_deets(market, detail['name'], 100, 0.1)

                # NOTE: This looks hacky and risky
                #if deet has None for one these values below, call it with min size of 20
                if deets['best_bid'] is None or deets['best_ask'] is None or deets['best_bid_size'] is None or deets['best_ask_size'] is None:
                    deets = get_best_bid_ask_deets(market, detail['name'], 20, 0.1)
                
                # Extract all order book details
                best_bid = deets['best_bid']
                best_bid_size = deets['best_bid_size']
                second_best_bid = deets['second_best_bid']
                second_best_bid_size = deets['second_best_bid_size'] 
                top_bid = deets['top_bid']
                best_ask = deets['best_ask']
                best_ask_size = deets['best_ask_size']
                second_best_ask = deets['second_best_ask']
                second_best_ask_size = deets['second_best_ask_size']
                top_ask = deets['top_ask']
                
                # Round prices to appropriate precision
                best_bid = round(best_bid, round_length)
                best_ask = round(best_ask, round_length)

                # Calculate ratio of buy vs sell liquidity in the market
                try:
                    overall_ratio = (deets['bid_sum_within_n_percent']) / (deets['ask_sum_within_n_percent'])
                except Exception as e:
                    Logan.error(f"Error calculating overall liquidity ratio for {detail['name']}: using default value 0", namespace="trading")
                    overall_ratio = 0

                try:
                    second_best_bid = round(second_best_bid, round_length)
                    second_best_ask = round(second_best_ask, round_length)
                except Exception as e:
                    Logan.error(f"Error rounding second best prices for {detail['name']}: {e}", namespace="trading", exception=e)
                
                top_bid = round(top_bid, round_length)
                top_ask = round(top_ask, round_length)

                # Get our current position and average price
                pos = get_position(token)
                position = pos['size']
                avgPrice = pos['avgPrice']
                
                position = round_down(position, 2)
               
                # Calculate optimal bid and ask prices based on market conditions
                bid_price, ask_price = get_order_prices(
                    best_bid, top_bid, best_ask, 
                    top_ask, avgPrice, row
                )

                bid_price = round(bid_price, round_length)
                ask_price = round(ask_price, round_length)

                # Calculate mid price for reference
                mid_price = (top_bid + top_ask) / 2
                
                # Log market conditions for this outcome
                #       f"avgPrice: {avgPrice}, Best Bid: {best_bid}, Best Ask: {best_ask}, "
                #       f"Bid Price: {bid_price}, Ask Price: {ask_price}, Mid Price: {mid_price}")

                # Get position for the opposite token to calculate total exposure
                other_token = global_state.REVERSE_TOKENS[str(token)]
                other_position = get_position(other_token)['size']
                
                # Calculate how much to buy or sell based on our position
                buy_amount, sell_amount = get_buy_sell_amount(position, row, force_sell=sell_only)
                
                # Get max_size for logging (same logic as in get_buy_sell_amount)
                trade_size = row.get('trade_size', position)
                max_size = row.get('max_size', trade_size)

                # Prepare order object with all necessary information
                order = {
                    "token": token,
                    "mid_price": mid_price,
                    "neg_risk": row['neg_risk'],
                    "max_spread": row['max_spread'],
                    'orders': orders,
                    'token_name': detail['name'],
                    'row': row
                }
            
                #       f"Trade Size: {trade_size}, Max Size: {max_size}, "
                #       f"buy_amount: {buy_amount}, sell_amount: {sell_amount}")

                # File to store risk management information for this market
                fname = 'positions/' + str(market) + '.json'

                # ------- SELL ONLY MODE -------
                # The market is no longer attractive, we want to get out of it to free up capital. 
                if sell_only and sell_amount > 0:
                    order['size'] = sell_amount
                    order['price'] = ask_price
                    send_sell_order(order)
                    continue

                # ------- SELL ORDER LOGIC TODO: This is completely bullshit. We should just rewrite it. -------
                if sell_amount > 0:
                    # Skip if we have no average price (no real position)
                    if avgPrice == 0:
                        Logan.warn("Avg Price is 0. Skipping", namespace="trading")
                        continue

                    order['size'] = sell_amount
                    order['price'] = ask_price

                    # Get fresh market data for risk assessment
                    n_deets = get_best_bid_ask_deets(market, detail['name'], 100, 0.1)
                    
                    # Calculate current market price and spread
                    mid_price = round_up((n_deets['best_bid'] + n_deets['best_ask']) / 2, round_length)
                    spread = round(n_deets['best_ask'] - n_deets['best_bid'], 2) # TODO: this seems wrong? 

                    # Calculate current profit/loss on position
                    pnl = (mid_price - avgPrice) / avgPrice * 100

                    
                    # Prepare risk details for tracking
                    risk_details = {
                        'time': str(pd.Timestamp.utcnow().tz_localize(None)),
                        'question': row['question']
                    }

                    try:
                        ratio = (n_deets['bid_sum_within_n_percent']) / (n_deets['ask_sum_within_n_percent'])
                    except Exception as e:
                        Logan.error(f"Error calculating fresh liquidity ratio for {detail['name']} during sell logic: using default value 0", namespace="trading")
                        ratio = 0

                    pos_to_sell = sell_amount  # Amount to sell in risk-off scenario

                    # ------- STOP-LOSS LOGIC -------
                    # Trigger stop-loss if either:
                    # 1. PnL is below threshold and spread is tight enough to exit
                    # 2. Volatility is too high
                    if sell_only or (pnl < params['stop_loss_threshold'] and spread <= params['spread_threshold']) or row['3_hour'] > params['volatility_threshold']:
                        risk_details['msg'] = (f"Selling {pos_to_sell} because spread is {spread} and pnl is {pnl} "
                                              f"and ratio is {ratio} and 3 hour volatility is {row['3_hour']}, and sell_only is {sell_only}")

                        # Sell at market best bid to ensure execution
                        order['size'] = pos_to_sell
                        order['price'] = n_deets['best_bid']

                        # Set period to avoid trading after stop-loss
                        risk_details['sleep_till'] = str(pd.Timestamp.utcnow().tz_localize(None) + 
                                                        pd.Timedelta(hours=params['sleep_period']))

                        # Risking off
                        # TODO: cancelling orders after sending sell order? 
                        send_sell_order(order)
                        client.cancel_all_market(market)

                        # Save risk details to file
                        open(fname, 'w').write(json.dumps(risk_details))
                        continue

                # ------- BUY ORDER LOGIC -------
                # Only buy if:
                # 1. Position is less than max_size (new logic)
                # 2. Buy amount is above minimum size
                if position < max_size and buy_amount > 0 and buy_amount >= row['min_size']:
                    # Get reference price from market data
                    sheet_value = row['best_bid']

                    if detail['name'] == 'token2':
                        sheet_value = 1 - row['best_ask']

                    sheet_value = round(sheet_value, round_length)
                    order['size'] = buy_amount
                    order['price'] = bid_price

                    # Check if price is far from reference
                    price_change = abs(order['price'] - sheet_value)

                    send_buy = True

                    # ------- RISK-OFF PERIOD CHECK -------
                    # If we're in a risk-off period (after stop-loss), don't buy
                    if os.path.isfile(fname):
                        risk_details = json.load(open(fname))

                        start_trading_at = pd.to_datetime(risk_details['sleep_till'])
                        current_time = pd.Timestamp.utcnow().tz_localize(None)

                        if current_time < start_trading_at:
                            send_buy = False
                            Logan.info(f"Not sending a buy order because recently risked off. ", namespace="trading")

                    # Only proceed if we're not in risk-off period
                    if send_buy:
                        # TODO: This doesn't make much sense to me, return to it. Probably we don't really need it with the automated market selection
                        # Don't buy if volatility is high or price is far from reference
                        # if row['3_hour'] > params['volatility_threshold'] or price_change >= 0.05:
                        #     client.cancel_all_asset(order['token'])
                        # else:

                        # Check for reverse position (holding opposite outcome)
                        rev_token = global_state.REVERSE_TOKENS[str(token)]
                        rev_pos = get_position(rev_token)

                        # If we have significant opposing position, and box sum guard fails, don't buy more
                        if rev_pos['size'] > row['min_size'] and order['price'] + rev_pos['avgPrice'] >= 0.99:
                            if orders['buy']['size'] > CONSTANTS.MIN_MERGE_SIZE:
                                client.cancel_all_asset(order['token'])
                            
                            continue
                        
                        # Check market buy/sell volume ratio
                        if overall_ratio < 0:
                            send_buy = False
                            client.cancel_all_asset(order['token'])
                        else:
                            # Place new buy order if any of these conditions are met:
                            # 1. We can get a better price than current order
                            if best_bid > orders['buy']['price']:
                                Logan.info(f"Sending Buy Order for {token} because better price. ", namespace="trading")
                                send_buy_order(order)
                            # 2. Current position + orders is not enough to reach max_size
                            elif position + orders['buy']['size'] < max_size:
                                Logan.info(f"Sending Buy Order for {token} because not enough position + size", namespace="trading")
                                send_buy_order(order)
                            # 3. Our current order is too large and needs to be resized
                            elif orders['buy']['size'] > order['size'] * 1.01:
                                Logan.info(f"Resending buy orders because open orders are too large", namespace="trading")
                                send_buy_order(order)
                            # Commented out logic for cancelling orders when market conditions change
                            # elif best_bid_size < orders['buy']['size'] * 0.98 and abs(best_bid - second_best_bid) > 0.03:
                            #     global_state.client.cancel_all_asset(order['token'])
                        
                # ------- TAKE PROFIT / SELL ORDER MANAGEMENT -------            
                elif sell_amount > 0:
                    order['size'] = sell_amount
                    
                    # Calculate take-profit price based on average cost
                    tp_price = round_up(avgPrice + (avgPrice * params['take_profit_threshold']/100), round_length)
                    order['price'] = round_up(tp_price if ask_price < tp_price else ask_price, round_length)
                    
                    tp_price = float(tp_price)
                    order_price = float(orders['sell']['price'])
                    
                    # Calculate % difference between current order and ideal price
                    diff = abs(order_price - tp_price)/tp_price * 100

                    # Update sell order if:
                    # 1. Current order price is significantly different from target
                    if diff > 2:
                        Logan.info(f"Sending Sell Order for {token} because better current order price of ", namespace="trading")
                        send_sell_order(order)
                    # 2. Current order size is too small for our position
                    elif orders['sell']['size'] < position * 0.97:
                        Logan.info(f"Sending Sell Order for {token} because not enough sell size. ", namespace="trading")
                        send_sell_order(order)
                    
                    # Commented out additional conditions for updating sell orders
                    # elif orders['sell']['price'] < ask_price:
                    #     send_sell_order(order)
                    # elif best_ask_size < orders['sell']['size'] * 0.98 and abs(best_ask - second_best_ask) > 0.03...:
                    #     send_sell_order(order)

        except Exception as ex:
            Logan.error(f"Critical error in perform_trade function for market {market} ({row.get('question', 'unknown question') if 'row' in locals() else 'unknown question'}): {ex}", namespace="trading", exception=ex)

        # Clean up memory and introduce a small delay
        gc.collect()
        await asyncio.sleep(2)