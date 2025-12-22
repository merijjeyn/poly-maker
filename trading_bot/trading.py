import gc                       # Garbage collection
import os                       # Operating system interface
import json                     # JSON handling
import asyncio                  # Asynchronous I/O
from growthbook.common_types import Experiment, Result, UserContext
from opentelemetry import trace
from opentelemetry.trace.status import Status, StatusCode
import pandas as pd             # Data analysis library
from logan import Logan         # Logging

import trading_bot.global_state as global_state
from configuration import TCNF

# Import utility functions for trading
from trading_bot.orders_in_flight import set_order_in_flight
from trading_bot.market_strategy.strategy_factory import StrategyFactory
from trading_bot.trading_utils import get_best_bid_ask_deets, round_down, round_up
from trading_bot.data_utils import get_position, get_order, get_readable_from_condition_id, get_total_balance
from trading_bot.market_selection import get_enhanced_market_row
from utils import nonethrows
from growthbook import GrowthBook


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
        price_diff > TCNF.BUY_PRICE_DIFF_THRESHOLD or  # Cancel if price diff > 0.2 cents
        size_diff > order['size'] * TCNF.SIZE_DIFF_PERCENTAGE or  # Cancel if size diff > 10%
        existing_buy_size == 0  # Cancel if no existing buy order
    )
    
    if should_cancel and (existing_buy_size > 0 or order['orders']['sell']['size'] > 0):
        Logan.info(f"Cancelling buy orders - price diff: {price_diff:.4f}, size diff: {size_diff:.1f}", namespace="trading")
        client.cancel_all_asset(order['token'])
    elif not should_cancel:
        return  # Don't place new order if existing one is fine

    if order['price'] >= TCNF.MIN_PRICE_LIMIT and order['price'] < TCNF.MAX_PRICE_LIMIT:
        resp = client.create_order(
            order['token'], 
            'BUY', 
            order['price'], 
            order['size'], 
            True if order['neg_risk'] == 'TRUE' else False
        )
        order['side'] = 'buy'
        handle_create_order_response(resp, order)
    else:
        Logan.warn(f"Not creating buy order because its outside acceptable price range ({TCNF.MIN_PRICE_LIMIT}-{TCNF.MAX_PRICE_LIMIT})", namespace="trading")


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
        price_diff > TCNF.SELL_PRICE_DIFF_THRESHOLD or  # Cancel if price diff > 0.1 cents
        size_diff > order['size'] * TCNF.SIZE_DIFF_PERCENTAGE or  # Cancel if size diff > 10%
        existing_sell_size == 0  # Cancel if no existing sell order
    )
    
    if should_cancel and (existing_sell_size > 0 or order['orders']['buy']['size'] > 0):
        Logan.info(f"Cancelling sell orders - price diff: {price_diff:.4f}, size diff: {size_diff:.1f}", namespace="trading")
        client.cancel_all_asset(order['token'])
    elif not should_cancel:
        return  # Don't place new order if existing one is fine

    resp = client.create_order(
        order['token'], 
        'SELL', 
        order['price'], 
        order['size'], 
        True if order['neg_risk'] == 'TRUE' else False
    )
    order['side'] = 'sell'
    handle_create_order_response(resp, order)

def handle_create_order_response(resp, order):
    if 'success' in resp and resp['success']: 
        set_order_in_flight(order['market'], resp['orderID'], order['side'], order['price'], order['size'])
    else: 
        Logan.error(f"Error creating order for token: {order['token']}", namespace="trading")
        
        # TODO: some markets cause an issue. Fix it and clean up here.
        # market = order['market']
        # fname = 'positions/' + str(market) + '.json'
        
        # risk_details = {
        #     'time': str(pd.Timestamp.utcnow().tz_localize(None)),
        #     'question': order.get('row', {}).get('question', 'unknown'),
        #     'msg': f"Error creating {order.get('side', 'unknown')} order for token {order['token']}. Response: {resp}",
        #     'sleep_till': str(pd.Timestamp.utcnow().tz_localize(None) + pd.Timedelta(hours=2))
        # }
        
        # open(fname, 'w').write(json.dumps(risk_details))
        # Logan.info(f"Market {market} will not be traded until {risk_details['sleep_till']}", namespace="trading")

def on_experiment_viewed(experiment: Experiment, result: Result, user_context: UserContext):
    market = user_context.attributes['id']
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("experiment_viewed") as span:
        span.set_attribute("experiment_name", experiment.name if experiment.name is not None else "Unknown")
        span.set_attribute("experiment_id", experiment.key)
        span.set_attribute("variation_id", result.key)
        span.set_attribute("market", market)


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
    # Note: The task scheduler is used to prevent concurrent trading on the same market so locks should not be needed. But let's do a slow rollout
    async with market_locks[market]:
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("perform_trade") as span:
            span.set_attribute("market", market)

            try:
                client = global_state.client
                # Get market details from the configuration with enhanced position sizing
                row = get_enhanced_market_row(market)

                # Skip trading if market is not in selected markets (filtered out)
                if row is None:
                    Logan.warn(f"Market {market} not found in active markets, skipping", namespace="trading")
                    return

                # Initialize GrowthBook
                gb = GrowthBook(
                    api_host = "https://cdn.growthbook.io",
                    client_key = "sdk-85rzhxYd65xY3aE",
                    on_experiment_viewed = on_experiment_viewed
                )
                gb.load_features()
                gb.set_attributes({
                    "id": market,
                })

                # Check if market is in positions but not in selected markets (sell-only mode to free up capital)
                sell_only = False
                if hasattr(global_state, 'markets_with_positions') and hasattr(global_state, 'selected_markets_df'):
                    in_positions = market in global_state.markets_with_positions['condition_id'].values if global_state.markets_with_positions is not None else False
                    in_selected = market in global_state.selected_markets_df['condition_id'].values if global_state.selected_markets_df is not None else False
                    sell_only = in_positions and not in_selected    
                    span.set_attribute("sell_only_reason", "market not selected anymore")  
                
                # Also sell if we have used most of our budget
                total_balance = get_total_balance()
                if global_state.available_liquidity < total_balance * (1 - TCNF.SELL_ONLY_THRESHOLD):
                    sell_only = True
                    span.set_attribute("sell_only_reason", "not enough liquidity")

                if row['3_hour'] > TCNF.VOLATILITY_EXIT_THRESHOLD:
                    sell_only = True
                    span.set_attribute("sell_only_reason", "volatility too high")
                
                span.set_attribute("sell_only", sell_only)
                
                # Determine decimal precision from tick size
                round_length = len(str(row['tick_size']).split(".")[1])
                
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
                
                # Only merge if positions are above minimum threshold
                if float(amount_to_merge) > TCNF.MIN_MERGE_SIZE:
                    with tracer.start_as_current_span("merge_positions") as span:
                        pos_1_raw = client.get_position(row['token1'])[0]
                        pos_2_raw = client.get_position(row['token2'])[0]
                        amount_to_merge_raw = min(pos_1_raw, pos_2_raw)

                        if amount_to_merge_raw / 1e6 > TCNF.MIN_MERGE_SIZE:
                            Logan.info(f"Merging {amount_to_merge_raw} of {row['token1']} and {row['token2']}", namespace="trading")
                            try:
                                span.set_attribute("amount_to_merge_raw", amount_to_merge_raw)
                                client.merge_positions(amount_to_merge_raw, market, row['neg_risk'] == 'TRUE')
                            except Exception as e:
                                span.set_status(Status(StatusCode.ERROR, str(e)))
                                Logan.error(f"Error merging {amount_to_merge_raw} positions for market \"{get_readable_from_condition_id(market)}\"", namespace="trading", exception=e)
                    
                    # TODO: for now, let it get updated by the background task
                    # Update our local position tracking
                    # scaled = amount_to_merge / 10**6
                    # set_position(row['token1'], 'SELL', scaled, 0, 'merge')
                    # set_position(row['token2'], 'SELL', scaled, 0, 'merge')
                    
                # ------- TRADING LOGIC FOR EACH OUTCOME -------
                # Loop through both outcomes in the market (YES and NO)
                for detail in deets: 
                    with tracer.start_as_current_span("perform_trade_for_token") as span:
                        token = str(detail['token'])

                        span.set_attribute("token", token)
                        
                        # Get current orders for this token
                        orders = get_order(token)
                        span.set_attribute("existing_buy_order_price", orders['buy']['price'])
                        span.set_attribute("existing_buy_order_size", orders['buy']['size'])
                        span.set_attribute("existing_sell_order_price", orders['sell']['price'])
                        span.set_attribute("existing_sell_order_size", orders['sell']['size'])

                        # Get market depth and price information
                        deets = get_best_bid_ask_deets(token, 100)

                        # NOTE: This looks hacky and risky
                        #if deet has None for one these values below, call it with min size of 20
                        if deets['best_bid'] is None or deets['best_ask'] is None or deets['best_bid_size'] is None or deets['best_ask_size'] is None:
                            deets = get_best_bid_ask_deets(token, 20)

                        logged_deets = {k: (v if v is not None else "None") for k, v in deets.items()}
                        span.set_attributes(logged_deets)
                        
                        # Extract all order book details
                        best_bid = round(deets['best_bid'], round_length) if deets['best_bid'] is not None else None
                        best_ask = round(deets['best_ask'], round_length) if deets['best_ask'] is not None else None
                        top_bid = round(deets['top_bid'], round_length) if deets['top_bid'] is not None else None
                        top_ask = round(deets['top_ask'], round_length) if deets['top_ask'] is not None else None

                        if top_bid is None or top_ask is None:
                            Logan.error(f"Top bid or top ask is None for token {token}", namespace="trading")
                            continue

                        # Get our current position and average price
                        pos = get_position(token)
                        position = pos['size']
                        position = round_down(position, 2)
                        span.set_attribute("position", position)

                        avgPrice = pos['avgPrice']
                        span.set_attribute("avg_price", avgPrice)
                        mid_price = (top_bid + top_ask) / 2
                        span.set_attribute("mid_price", mid_price)

                        # Calculate optimal bid and ask prices based on market conditions
                        bid_price, ask_price = StrategyFactory.get_with_gb(gb).get_order_prices(
                            best_bid, best_ask, mid_price, row, token, row['tick_size'], force_sell=sell_only
                        )
                        bid_price = round(bid_price, round_length)
                        ask_price = round(ask_price, round_length)
                        span.set_attribute("bid_price", bid_price)
                        span.set_attribute("ask_price", ask_price)

                        # Calculate how much to buy or sell based on our position
                        buy_amount, sell_amount = StrategyFactory.get_with_gb(gb).get_buy_sell_amount(position, row, force_sell=sell_only)
                        span.set_attribute("buy_amount", buy_amount)
                        span.set_attribute("sell_amount", sell_amount)

                        # Get max_size for logging (same logic as in get_buy_sell_amount)
                        trade_size = row.get('trade_size', position)
                        max_size = nonethrows(row.get('max_size', trade_size))

                        # Prepare order object with all necessary information
                        order = {
                            "market": market,
                            "token": token,
                            "mid_price": mid_price,
                            "neg_risk": row['neg_risk'],
                            "max_spread": row['max_spread'],
                            'orders': orders,
                            'token_name': detail['name'],
                            'row': row
                        }

                        # File to store risk management information for this market
                        fname = 'positions/' + str(market) + '.json'

                        # ------- STOP LOSS LOGIC -------
                        # pnl is too low, aggresively exit the market to minimize further risk.
                        top_spread = top_ask - top_bid
                        pnl = (mid_price - avgPrice) / avgPrice * 100 if avgPrice > 0 else 0
                        span.set_attribute("pnl", pnl)

                        if pnl < TCNF.STOP_LOSS_THRESHOLD and top_spread <= TCNF.STOP_LOSS_SPREAD_THRESHOLD:
                            pos_to_sell = position

                            risk_details = {
                                'time': str(pd.Timestamp.utcnow().tz_localize(None)),
                                'question': row['question']
                            }
                            risk_details['msg'] = (f"Selling {pos_to_sell} because spread is {top_spread} and pnl is {pnl} "
                                                f"and 3 hour volatility is {row['3_hour']}, and sell_only is {sell_only}")

                            # Sell at market best bid to ensure execution
                            order['size'] = pos_to_sell
                            order['price'] = top_bid

                            # Set period to avoid trading after stop-loss
                            risk_details['sleep_till'] = str(pd.Timestamp.utcnow().tz_localize(None) + 
                                                            pd.Timedelta(minutes=TCNF.STOP_LOSS_SLEEP_PERIOD_MINS))

                            # Risking off
                            send_sell_order(order)

                            # Save risk details to file
                            open(fname, 'w').write(json.dumps(risk_details))
                            span.add_event("stop_loss_sell_order_sent", {
                                "pnl": pnl, 
                                "pnl_threshold": TCNF.STOP_LOSS_THRESHOLD,
                                "spread": top_spread,
                                "spread_threshold": TCNF.STOP_LOSS_SPREAD_THRESHOLD,
                                "3_hour_volatility": str(row['3_hour']),
                                "volatility_threshold": TCNF.VOLATILITY_EXIT_THRESHOLD,
                                "sleep_period_mins": TCNF.STOP_LOSS_SLEEP_PERIOD_MINS,
                                "expected_pnl": (order['price'] - avgPrice) / avgPrice * 100 if avgPrice > 0 else 0,
                            })
                            continue

                        # ------- SELL ONLY MODE -------
                        # The market is no longer attractive, we want to get out of it to free up capital. 
                        if sell_only and sell_amount > 0:
                            order['size'] = sell_amount
                            order['price'] = ask_price
                            send_sell_order(order)
                            span.add_event("sell_only_sell_order_sent", {
                                "price": order['price'],
                                "size": order['size'],
                                "mid_price": mid_price,
                                "max_spread": order['max_spread'],
                                "neg_risk": order['neg_risk'],
                                "expected_pnl": (order['price'] - avgPrice) / avgPrice * 100 if avgPrice > 0 else 0,
                            })
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
                            send_buy = True

                            # ------- RISK-OFF PERIOD CHECK -------
                            # If we're in a risk-off period (after stop-loss), don't buy
                            if os.path.isfile(fname):
                                risk_details = json.load(open(fname))

                                start_trading_at = pd.to_datetime(risk_details['sleep_till'])
                                current_time = pd.Timestamp.utcnow().tz_localize(None)

                                if current_time < start_trading_at:
                                    send_buy = False
                                    Logan.info("Not sending a buy order because recently risked off. ", namespace="trading")

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
                                if rev_pos['size'] > row['min_size'] and order['price'] + rev_pos['avgPrice'] >= TCNF.PRICE_PRECISION_LIMIT:
                                    if orders['buy']['size'] > TCNF.MIN_MERGE_SIZE:
                                        client.cancel_all_asset(order['token'])
                                    continue

                                if position + orders['buy']['size'] < max_size:
                                    send_buy_order(order)
                                    span.add_event("buy_order_sent", {
                                        "price": order['price'],
                                        "size": order['size'],
                                        "mid_price": mid_price,
                                        "max_spread": order['max_spread'],
                                        "neg_risk": order['neg_risk'],
                                    })
                            
                        # ------- SELL ORDER MANAGEMENT -------            
                        elif sell_amount > 0:
                            order['size'] = sell_amount
                            order['price'] = ask_price

                            send_sell_order(order)
                            span.add_event("sell_order_sent", {
                                "price": order['price'],
                                "size": order['size'],
                                "mid_price": mid_price,
                                "max_spread": order['max_spread'],
                                "neg_risk": order['neg_risk'],
                                "expected_pnl": (order['price'] - avgPrice) / avgPrice * 100 if avgPrice > 0 else 0,
                            })

            except Exception as ex:
                Logan.error(f"Critical error in perform_trade function for market {market} ({row.get('question', 'unknown question') if 'row' in locals() else 'unknown question'}): {ex}", namespace="trading", exception=ex)  # type: ignore

        gc.collect()