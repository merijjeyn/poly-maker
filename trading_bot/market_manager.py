"""
Market Management Module

This module handles market selection and position sizing logic.
Separated from data_utils to avoid circular imports between:
- data_utils (basic data operations)
- market_selection (filtering and sizing logic)
- market_strategy (trading strategies that use data_utils)
"""

import trading_bot.global_state as global_state
from google_utils import get_sheet_df
from trading_bot.market_selection import calculate_position_sizes, filter_selected_markets
from trading_bot.data_utils import update_liquidity
import logging


def update_markets_with_positions():
    if global_state.positions:
        position_tokens = []
        for token, position in global_state.positions.items():
            if position['size'] > 0:
                position_tokens.append(str(token))
        
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
        
        logging.info(f"Updated markets from sheet. Total markets: {len(global_state.df)}", extra={"namespace": "market_manager"})

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

