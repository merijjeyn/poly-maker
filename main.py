import gc                      # Garbage collection
import time                    # Time functions
import asyncio                 # Asynchronous I/O
import threading               # Thread management
import argparse                # Command line argument parsing
from logan import Logan


from trading_bot.polymarket_client import PolymarketClient
from trading_bot.data_utils import update_positions, update_orders, clear_all_orders
from trading_bot.market_manager import update_markets
from trading_bot.websocket_handlers import connect_market_websocket, connect_user_websocket
import trading_bot.global_state as global_state
from trading_bot.data_processing import remove_from_performing
from trading_bot.market_strategy.strategy_factory import StrategyFactory, StrategyType
from dotenv import load_dotenv
from configuration import MCNF
from telemetry import setup_telemetry
import logging

def update_once():
    """
    Initialize the application state by fetching market data, positions, and orders.
    """
    update_markets()    # Get market information from Google Sheets
    update_positions()  # Get current positions from Polymarket
    update_orders()     # Get current orders from Polymarket

def remove_from_pending():
    """
    Clean up stale trades that have been pending for too long (>15 seconds).
    This prevents the system from getting stuck on trades that may have failed.
    """
    try:
        current_time = time.time()
            
        # Iterate through all performing trades
        for col in list(global_state.performing.keys()):
            for trade_id in list(global_state.performing[col]):
                
                try:
                    # If trade has been pending for more than 15 seconds, remove it
                    if current_time - global_state.performing_timestamps[col].get(trade_id, current_time) > MCNF.STALE_TRADE_TIMEOUT:
                        Logan.info(f"Removing stale entry {trade_id} from {col} after 15 seconds", namespace="cleanup")
                        logging.info(f"Removing stale entry {trade_id} from {col} after 15 seconds", extra={"namespace": "cleanup"})
                        remove_from_performing(col, trade_id)
                except Exception as e:
                    Logan.error(f"Error removing stale trade {trade_id} from {col}", namespace="cleanup", exception=e)
                    logging.error(f"Error removing stale trade {trade_id} from {col}", exc_info=e, extra={"namespace": "cleanup"})
    except Exception as e:
        Logan.error("Error in remove_from_pending function while cleaning stale trades", namespace="cleanup", exception=e)
        logging.error("Error in remove_from_pending function while cleaning stale trades", exc_info=e, extra={"namespace": "cleanup"})

def update_periodically():
    """
    Background thread function that periodically updates market data, positions and orders.
    - Positions and orders are updated every 5 seconds
    - Market data is updated every 30 seconds (every 6 cycles)
    - Stale pending trades are removed each cycle
    """
    i = 1
    while True:
        time.sleep(MCNF.POSITION_UPDATE_INTERVAL)  # Update every 5 seconds
        
        try:
            # Clean up stale trades
            remove_from_pending()
            
            # Update positions and orders every cycle
            update_positions()
            update_orders()

            # Update market data every 6th cycle (30 seconds)
            if i % MCNF.MARKET_UPDATE_CYCLE_COUNT == 0:
                update_markets()
                i = 1
                    
            gc.collect()  # Force garbage collection to free memory
            i += 1
        except Exception as e:
            Logan.error(f"Error in update_periodically background thread (cycle {i})", namespace="updater", exception=e)
            logging.error(f"Error in update_periodically background thread (cycle {i})", exc_info=e, extra={"namespace": "updater"})
            
async def main():
    """
    Main application entry point. Initializes client, data, and manages websocket connections.
    """

    parser = argparse.ArgumentParser(description="Polymarket Market Making Bot")
    parser.add_argument("--env", default=".env", help="Path to environment file (default: .env)")
    parser.add_argument("--nologan", action="store_true", default=False, help="Disable Logan server and log to console")
    parser.add_argument(
        "--strategy", 
        type=StrategyType,
        default=StrategyType.ANS,
        choices=list(StrategyType), 
        help=f"Market making strategy to use (default: {StrategyType.ANS})"
    )
    parser.add_argument("--clear-orders", action="store_true", default=False, help="Clear all existing orders on startup")
    args = parser.parse_args()
    
    load_dotenv(dotenv_path=args.env)

    # Initialize market strategy based on command-line argument
    StrategyFactory.init(args.strategy)
    Logan.info(f"Initialized market strategy: {args.strategy}", namespace="init")
    logging.info(f"Initialized market strategy: {args.strategy}", extra={"namespace": "init"})

    # Initialize client
    global_state.client = PolymarketClient(env_path=args.env)
    
    # Initialize state and fetch initial data
    global_state.all_tokens = []
    
    setup_telemetry(nologan=args.nologan)
    
    update_once()

    # Clear all existing orders on startup if requested
    if args.clear_orders:
        clear_all_orders()

    Logan.info(f"After initial updates: orders={global_state.orders}, positions={global_state.positions}", namespace="init")

    Logan.info(f'There are {len(global_state.df)} markets, {len(global_state.positions)} positions and {len(global_state.orders)} orders. Starting positions: {global_state.positions}', namespace="init")

    # Start background update thread
    update_thread = threading.Thread(target=update_periodically, daemon=True)
    update_thread.start()
    
    # Websocket connections. Each connection has an internal loop that will attempt to reconnect if the connection is lost.
    await asyncio.gather(
        connect_market_websocket(global_state.all_tokens), 
        connect_user_websocket()
    )
    
if __name__ == "__main__":
    asyncio.run(main())