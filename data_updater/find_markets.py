import pandas as pd
import numpy as np
import requests
import time
import warnings
from logan import Logan

from data_updater.activity_metrics import add_activity_metrics_to_market_data
from configuration import TCNF
warnings.filterwarnings("ignore")

    
def get_all_markets(client) -> pd.DataFrame:
    cursor = ""
    all_markets = []

    while True:
        try:
            markets = client.get_sampling_markets(next_cursor = cursor)
            markets_df = pd.DataFrame(markets['data'])

            cursor = markets['next_cursor']
            
            all_markets.append(markets_df)

            if cursor == "LTE=":
                break
        except Exception as e:
            Logan.error(
                f"Error fetching market batch with cursor '{cursor}'",
                namespace="data_updater.find_markets",
                exception=e
            )
            break

    all_df = pd.concat(all_markets)
    all_df = all_df.reset_index(drop=True)

    return all_df

def get_bid_ask_range(ret, TICK_SIZE):
    bid_from = ret['midpoint'] - ret['max_spread'] / 100
    bid_to = ret['best_ask'] #Although bid to this high up will change bid_from because of changing midpoint, take optimistic approach

    if bid_to == 0:
        bid_to = ret['midpoint']

    if bid_to - TICK_SIZE > ret['midpoint']:
        bid_to = ret['best_bid'] + (TICK_SIZE + 0.1 * TICK_SIZE)

    if bid_from > bid_to:
        bid_from = bid_to - (TICK_SIZE + 0.1 * TICK_SIZE)

    ask_to = ret['midpoint'] + ret['max_spread'] / 100
    ask_from = ret['best_bid']

    if ask_from == 0:
        ask_from = ret['midpoint']

    if ask_from + TICK_SIZE < ret['midpoint']:
        ask_from = ret['best_ask'] - (TICK_SIZE + 0.1 * TICK_SIZE)

    if ask_from > ask_to:
        ask_to = ask_from + (TICK_SIZE + 0.1 * TICK_SIZE)

    bid_from = round(bid_from, 3)
    bid_to = round(bid_to, 3)
    ask_from = round(ask_from, 3)
    ask_to = round(ask_to, 3)

    if bid_from < 0:
        bid_from = 0

    if ask_from < 0:
        ask_from = 0
        
    return bid_from, bid_to, ask_from, ask_to


def generate_numbers(start, end, TICK_SIZE):
    # Calculate the starting point, rounding up to the next hundredth if not an exact multiple of TICK_SIZE
    rounded_start = (int(start * 100) + 1) / 100 if start * 100 % 1 != 0 else start + TICK_SIZE
    
    # Calculate the ending point, rounding down to the nearest hundredth
    rounded_end = int(end * 100) / 100
    
    # Generate numbers from rounded_start to rounded_end, ensuring they fall strictly within the original bounds
    numbers = []
    current = rounded_start
    while current < end:
        numbers.append(current)
        current += TICK_SIZE
        current = round(current, len(str(TICK_SIZE).split('.')[1]))  # Rounding to avoid floating point imprecision

    return numbers

# TODO: This reward calculation is awful. Reevaluate it. 
def calculate_reward_per_100(curr_df, midpoint, max_spread, daily_reward):
    max_spread_usd = round((max_spread / 100), 2)
    curr_df['s'] = (curr_df['price'] - midpoint).abs()
    curr_df['S'] = ((max_spread_usd - curr_df['s']) / max_spread_usd) ** 2
    # curr_df['S'] = curr_df['S'].where(curr_df['s'] <= v, 0)  # Set to 0 when s > v
    
    curr_df['100'] = 1/curr_df['price'] * 100
    curr_df['size'] = curr_df['size'] + curr_df['100']

    curr_df['Q'] = curr_df['S'] * curr_df['size']
    curr_df['reward_per_100'] = (curr_df['Q'] / curr_df['Q'].sum()) * daily_reward / 2 / curr_df['size'] * curr_df['100']
    return curr_df

def calculate_market_depth(bids_df, asks_df, midpoint, max_spread):
    max_spread_usd = round((max_spread / 100), 2)
    """Calculate depth_yes_in and depth_no_in based on midpoint and s_max"""
    depth_yes_in = 0
    depth_no_in = 0
    
    # Calculate price ranges
    price_low_yes = midpoint - max_spread_usd
    price_high_yes = midpoint
    price_low_no = midpoint
    price_high_no = midpoint + max_spread_usd
    
    # Sum yes bids within range [mid - s_max, mid]
    if not bids_df.empty:
        filtered_bids = bids_df[(bids_df['price'] >= price_low_yes) & (bids_df['price'] <= price_high_yes)]
        depth_yes_in = filtered_bids['size'].sum()
    
    # Sum no asks within range [mid, mid + s_max]
    if not asks_df.empty:
        filtered_asks = asks_df[(asks_df['price'] >= price_low_no) & (asks_df['price'] <= price_high_no)]
        depth_no_in = filtered_asks['size'].sum()
    
    return depth_yes_in, depth_no_in

def calculate_market_imbalance(bids_df, asks_df, midpoint):
    # The window to look for imbalance is the hybrid of fixed number of price levels,
    # and a fixed spread size calculated from the percentage of midpoint
    bids_sorted = bids_df[bids_df['price'] <= midpoint].sort_values('price', ascending=False)
    level_window_lower = bids_sorted['price'].head(TCNF.MARKET_IMBALANCE_CALC_LEVELS).min() if not bids_sorted.empty else midpoint

    asks_sorted = asks_df[asks_df['price'] >= midpoint].sort_values('price', ascending=True)
    level_window_upper = asks_sorted['price'].head(TCNF.MARKET_IMBALANCE_CALC_LEVELS).max() if not asks_sorted.empty else midpoint

    spread_size = min(midpoint, 1-midpoint) * TCNF.MARKET_IMBALANCE_CALC_PCT
    pct_window_lower = midpoint - spread_size/2
    pct_window_upper = midpoint + spread_size/2

    window_lower = max(level_window_lower, pct_window_lower)
    window_upper = min(level_window_upper, pct_window_upper)

    bids_in_window = bids_df[(bids_df['price'] >= window_lower) & (bids_df['price'] <= window_upper)]
    bids_size_in_window = bids_in_window['size'].sum()
    asks_in_window = asks_df[(asks_df['price'] >= window_lower) & (asks_df['price'] <= window_upper)]
    asks_size_in_window = asks_in_window['size'].sum()

    imbalance = (bids_size_in_window - asks_size_in_window) / (bids_size_in_window + asks_size_in_window)
    return imbalance
    

def calculate_attractiveness_score(rewards_daily_rate, spread, max_spread, tick_size, midpoint, 
                                 depth_yes_in, depth_no_in, volatility=None, 
                                 in_game_multiplier=1.0, plan_two_sided=True, alpha=0.1):
    """Calculate attractiveness score based on market conditions and strategy"""
    max_spread_usd = round((max_spread / 100), 2)
    vol = volatility if volatility is not None else 0.0
    
    # Skip non-viable markets
    if max_spread_usd <= tick_size or spread > max_spread_usd:
        return 0.0
    if midpoint < 0.10 or midpoint > 0.90:
        return 0.0
    
    # 1) How much scoring boost can you capture if you quote inside incentive spread?
    w_target = max(tick_size, min(max_spread_usd - tick_size, spread / 2))
    boost = ((max_spread_usd - w_target) / max_spread_usd) ** 2
    
    # 2) Two-sided factor (penalty if one-sided while mid in [0.10, 0.90])
    two_sided_req = (midpoint <= 0.10 or midpoint >= 0.90)
    two_side_multiplier = 1.0 if (plan_two_sided or two_sided_req) else (1/3.0)
    
    # 3) Competition inside the reward zone
    sample_investment = 100
    D = max(sample_investment, depth_yes_in + depth_no_in)
    competition_factor = sample_investment / D
    
    # 4) Risk/friction penalty
    risk_penalty = alpha * vol
    
    # Final attractiveness score
    attractiveness_score = (
        rewards_daily_rate * in_game_multiplier * boost * two_side_multiplier * competition_factor
    ) / (1.0 + risk_penalty)

    # Scale up for visibility
    attractiveness_score = attractiveness_score * 10**3    
    return attractiveness_score

def process_market_row(row, client):    
    ret = {}
    ret['question'] = row['question']
    ret['neg_risk'] = row['neg_risk']

    assert len(row['tokens']) == 2, f"Expected 2 tokens for market {row['question']}, got {len(row['tokens'])}"
    
    ret['answer1'] = row['tokens'][0]['outcome']
    ret['answer2'] = row['tokens'][1]['outcome']

    ret['min_size'] = row['rewards']['min_size']
    ret['max_spread'] = row['rewards']['max_spread']

    token1 = row['tokens'][0]['token_id']
    token2 = row['tokens'][1]['token_id']

    rate = 0
    for rate_info in row['rewards']['rates']:
        if rate_info['asset_address'].lower() == '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174'.lower():
            rate = rate_info['rewards_daily_rate']
            break

    ret['rewards_daily_rate'] = rate
    book = client.get_order_book(token1)
    
    bids = pd.DataFrame()
    asks = pd.DataFrame()

    try:
        bids = pd.DataFrame(book.bids).astype(float)
    except Exception as e:
        raise ValueError(f"Error processing bids for token {token1}")

    try:
        asks = pd.DataFrame(book.asks).astype(float)
    except Exception as e:
        raise ValueError(f"Error processing asks for token {token1}")

    ret['best_bid'] = bids.iloc[-1]['price'] if not bids.empty else 0
    ret['best_ask'] = asks.iloc[-1]['price'] if not asks.empty else 1
    ret['midpoint'] = (ret['best_bid'] + ret['best_ask']) / 2
    
    TICK_SIZE = row['minimum_tick_size']
    ret['tick_size'] = TICK_SIZE

    bid_from, bid_to, ask_from, ask_to = get_bid_ask_range(ret, TICK_SIZE)

    bids_df = pd.DataFrame()
    bids_df['price'] = generate_numbers(bid_from, bid_to, TICK_SIZE)

    asks_df = pd.DataFrame()
    asks_df['price'] = generate_numbers(ask_from, ask_to, TICK_SIZE)

    try:
        bids_df = bids_df.merge(bids, on='price', how='left').fillna(0)
    except Exception as e:
        Logan.error(
            f"Error merging bids data for token {token1}",
            namespace="data_updater.find_markets",
            exception=e
        )
        bids_df = pd.DataFrame()

    try:
        asks_df = asks_df.merge(asks, on='price', how='left').fillna(0)
    except Exception as e:
        Logan.error(
            f"Error merging asks data for token {token1}",
            namespace="data_updater.find_markets",
            exception=e
        )
        asks_df = pd.DataFrame()

    best_bid_reward = 0
    ret_bid = pd.DataFrame()

    try:
        ret_bid = calculate_reward_per_100(bids_df, ret['midpoint'], ret['max_spread'], rate)
        best_bid_reward = round(ret_bid['reward_per_100'].max(), 2)
    except Exception as e:
        Logan.error(
            f"Error calculating bid rewards for token {token1}",
            namespace="data_updater.find_markets",
            exception=e
        )

    best_ask_reward = 0
    ret_ask = pd.DataFrame()

    try:
        ret_ask = calculate_reward_per_100(asks_df, ret['midpoint'], ret['max_spread'], rate)
        best_ask_reward = round(ret_ask['reward_per_100'].max(), 2)
    except Exception as e:
        Logan.error(
            f"Error calculating ask rewards for token {token1}",
            namespace="data_updater.find_markets",
            exception=e
        )

    ret['bid_reward_per_100'] = best_bid_reward
    ret['ask_reward_per_100'] = best_ask_reward

    ret['sm_reward_per_100'] = round((best_bid_reward + best_ask_reward) / 2, 2)
    ret['gm_reward_per_100'] = round((best_bid_reward * best_ask_reward) ** 0.5, 2)
    
    # Calculate market depth within reward zone
    depth_yes_in, depth_no_in = calculate_market_depth(bids, asks, ret['midpoint'], ret['max_spread'])
    ret['depth_yes_in'] = depth_yes_in
    ret['depth_no_in'] = depth_no_in

    # Calculate attractiveness score
    ret['spread'] = abs(ret['best_ask'] - ret['best_bid'])
    ret['attractiveness_score'] = calculate_attractiveness_score(
        rewards_daily_rate=ret['rewards_daily_rate'],
        spread=ret['spread'],
        max_spread=ret['max_spread'],
        tick_size=TICK_SIZE,
        midpoint=ret['midpoint'],
        depth_yes_in=depth_yes_in,
        depth_no_in=depth_no_in
    )

    ret['market_order_imbalance'] = calculate_market_imbalance(bids_df, asks_df, ret['midpoint'])

    ret['end_date_iso'] = row['end_date_iso']
    ret['market_slug'] = row['market_slug']
    ret['token1'] = token1
    ret['token2'] = token2
    ret['condition_id'] = row['condition_id']

    # Add volatility data using existing add_volatility function
    try:
        volatility_data = add_volatility(ret)
        ret.update(volatility_data)
    except Exception as e:
        Logan.error(
            f"Error adding volatility data for token {token1}",
            namespace="data_updater.find_markets",
            exception=e
        )
    ret['volatility_sum'] =  ret['24_hour'] + ret['7_day'] + ret['14_day']
    ret['volatilty/reward'] = ((ret['gm_reward_per_100'] / ret['volatility_sum']).round(2)).astype(str)

    # Add activity metrics using existing function
    try:
        ret = add_activity_metrics_to_market_data(ret)
    except Exception as e:
        Logan.error(
            f"Error adding activity metrics for token {token1}",
            namespace="data_updater.find_markets",
            exception=e
        )

    return ret


# This function is used to get detailed information for all markets through targeted apis like order book, trading history, etc.
def get_all_markets_detailed(all_df: pd.DataFrame, client, max_workers=3, batch_size=40) -> pd.DataFrame:
    all_results = []
    
    def process_with_progress(args):
        idx, row = args
        try:
            return process_market_row(row, client)
        except Exception as e:
            Logan.error(
                f"Error fetching market data for {row.get('question', 'unknown market')}",
                namespace="data_updater.find_markets",
                exception=e
            )
            return None

    # Process in batches to respect rate limits
    for i in range(0, len(all_df), batch_size):
        batch_df = all_df.iloc[i:i+batch_size]
        batch_start_time = time.perf_counter()
        batch_results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_with_progress, (idx, row)) for idx, row in batch_df.iterrows()]
            
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result is not None:
                    batch_results.append(result)
        
        all_results.extend(batch_results)
        Logan.info(
            f'{len(all_results)} of {len(all_df)} markets processed',
            namespace="data_updater.find_markets"
        )
        
        # Rate limit: ensure a minimum 15s window per batch (processing time counts)
        if i + batch_size < len(all_df):
            elapsed = time.perf_counter() - batch_start_time
            remaining = max(0.0, 15.0 - elapsed)
            if remaining > 0:
                Logan.info(
                    f"Waiting {remaining:.2f} seconds to respect rate limits...",
                    namespace="data_updater.find_markets"
                )
                time.sleep(remaining)

    return pd.DataFrame(all_results)


import concurrent.futures

def calculate_annualized_volatility(df, hours):
    end_time = df['t'].max()
    start_time = end_time - pd.Timedelta(hours=hours)
    window_df = df[df['t'] >= start_time]
    volatility = window_df['log_return'].std()
    annualized_volatility = volatility * np.sqrt(60 * 24 * 252)
    return round(annualized_volatility, 2)

def add_volatility(row):
    res = requests.get(f'https://clob.polymarket.com/prices-history?interval=1m&market={row["token1"]}&fidelity=10')
    price_df = pd.DataFrame(res.json()['history'])
    price_df['t'] = pd.to_datetime(price_df['t'], unit='s')
    price_df['p'] = price_df['p'].round(2)

    price_df['log_return'] = np.log(price_df['p'] / price_df['p'].shift(1))

    row_dict = row.copy()

    stats = {
        '1_hour': calculate_annualized_volatility(price_df, 1),
        '3_hour': calculate_annualized_volatility(price_df, 3),
        '6_hour': calculate_annualized_volatility(price_df, 6),
        '12_hour': calculate_annualized_volatility(price_df, 12),
        '24_hour': calculate_annualized_volatility(price_df, 24),
        '7_day': calculate_annualized_volatility(price_df, 24 * 7),
        '14_day': calculate_annualized_volatility(price_df, 24 * 14),
        '30_day': calculate_annualized_volatility(price_df, 24 * 30),
        'volatility_price': price_df['p'].iloc[-1]
    }

    new_dict = {**row_dict, **stats}
    return new_dict

def cleanup_all_markets(df: pd.DataFrame) -> pd.DataFrame:
    df = df.replace([np.inf, -np.inf], 0)
    df = df.sort_values('attractiveness_score', ascending=False)

    columns_to_fill_0 = ['market_order_imbalance', 'gm_reward_per_100', 'sm_reward_per_100', 'bid_reward_per_100', 'ask_reward_per_100']
    for col in columns_to_fill_0:
        df[col] = df[col].fillna(0)

    # Bring up important columns to front
    first_columns = [
        'question', 'answer1', 'answer2', 'attractiveness_score', 'spread', 'market_order_imbalance', 'rewards_daily_rate', 
        'gm_reward_per_100', 'sm_reward_per_100', 'bid_reward_per_100', 'ask_reward_per_100', 'min_size', 'max_spread', 
        'tick_size', 'market_slug', 'depth_yes_in', 'depth_no_in', 'condition_id', 'token1', 'token2'
    ]
    first_columns_in_df = [col for col in first_columns if col in df.columns]
    extra_columns = [col for col in df.columns if col not in first_columns_in_df]
    df = df[first_columns_in_df + extra_columns]

    return df
