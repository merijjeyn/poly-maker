import time
from dotenv import load_dotenv
import pandas as pd
from data_updater.trading_utils import get_clob_client
from google_utils import get_spreadsheet
from data_updater.find_markets import cleanup_all_markets, get_all_markets, get_all_markets_detailed
from gspread_dataframe import set_with_dataframe
from logan import Logan
from configuration import TCNF

# Initialize global variables
load_dotenv()
spreadsheet = get_spreadsheet()
client = get_clob_client()

wk_all = spreadsheet.worksheet("All Markets")


def update_sheet(data, worksheet):
    all_values = worksheet.get_all_values()
    existing_num_rows = len(all_values)
    existing_num_cols = len(all_values[0]) if all_values else 0

    num_rows, num_cols = data.shape
    max_rows = max(num_rows, existing_num_rows)
    max_cols = max(num_cols, existing_num_cols)

    # Create a DataFrame with the maximum size and fill it with empty strings
    padded_data = pd.DataFrame('', index=range(max_rows), columns=range(max_cols))

    # Update the padded DataFrame with the original data and its columns
    padded_data.iloc[:num_rows, :num_cols] = data.values
    padded_data.columns = list(data.columns) + [''] * (max_cols - num_cols)

    # Update the sheet with the padded DataFrame, including column headers
    set_with_dataframe(worksheet, padded_data, include_index=False, include_column_header=True, resize=True)

def sort_df(df):
    # Calculate the mean and standard deviation for each column
    mean_gm = df['gm_reward_per_100'].mean()
    std_gm = df['gm_reward_per_100'].std()
    
    mean_volatility = df['volatility_sum'].mean()
    std_volatility = df['volatility_sum'].std()
    
    # Standardize the columns
    df['std_gm_reward_per_100'] = (df['gm_reward_per_100'] - mean_gm) / std_gm
    df['std_volatility_sum'] = (df['volatility_sum'] - mean_volatility) / std_volatility
    
    # Define a custom scoring function for best_bid and best_ask
    def proximity_score(value):
        if 0.1 <= value <= 0.25:
            return (0.25 - value) / 0.15
        elif 0.75 <= value <= 0.9:
            return (value - 0.75) / 0.15
        else:
            return 0
    
    df['bid_score'] = df['best_bid'].apply(proximity_score)
    df['ask_score'] = df['best_ask'].apply(proximity_score)
    
    # Create a composite score (higher is better for rewards, lower is better for volatility, with proximity scores)
    df['composite_score'] = (
        df['std_gm_reward_per_100'] - 
        df['std_volatility_sum'] + 
        df['bid_score'] + 
        df['ask_score']
    )
    
    # Sort by the composite score in descending order
    sorted_df = df.sort_values(by='composite_score', ascending=False)
    
    # Drop the intermediate columns used for calculation
    sorted_df = sorted_df.drop(columns=['std_gm_reward_per_100', 'std_volatility_sum', 'bid_score', 'ask_score', 'composite_score'])
    
    return sorted_df

def fetch_and_process_data():
    global spreadsheet, client, wk_all, wk_vol, sel_df
    
    spreadsheet = get_spreadsheet()
    client = get_clob_client()

    wk_all = spreadsheet.worksheet("All Markets")

    all_markets_df = get_all_markets(client)
    Logan.info(
        f"Fetching information for {len(all_markets_df)} markets.",
        namespace="update_markets"
    )

    all_markets_df = get_all_markets_detailed(all_markets_df, client)
    all_markets_df = cleanup_all_markets(all_markets_df)
    Logan.info(
        f'{pd.to_datetime("now")}: Fetched all markets data with volatility and activity metrics of length {len(all_markets_df)}.',
        namespace="update_markets"
    )

    if len(all_markets_df) > 50:
        update_sheet(all_markets_df, wk_all)
    else:
        Logan.warn(
            f'Not updating sheet because of length {len(all_markets_df)}.',
            namespace="update_markets"
        )

if __name__ == "__main__":    
    while True:
        try:
            fetch_and_process_data()
            time.sleep(60 * 60)  # Sleep for an hour
        except Exception as e:
            Logan.error(
                f"Error in market data update loop",
                namespace="update_markets",
                exception=e
            )
