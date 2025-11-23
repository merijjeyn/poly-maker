import asyncio                      # Asynchronous I/O
import gc
import json                        # JSON handling
import websockets                  # WebSocket client
from logan import Logan

from trading_bot.data_processing import process_market_data, process_user_data
import trading_bot.global_state as global_state
from configuration import MCNF

async def connect_market_websocket(chunk):
    """
    Connect to Polymarket's market WebSocket API and process market updates.
    
    This function:
    1. Establishes a WebSocket connection to the Polymarket API
    2. Subscribes to updates for a specified list of market tokens
    3. Processes incoming order book and price updates
    
    Args:
        chunk (list): List of token IDs to subscribe to
        
    Notes:
        If the connection is lost, the while loop will attempt to reconnect
    """
    uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    while True:
        async with websockets.connect(uri, ping_interval=MCNF.WEBSOCKET_PING_INTERVAL, ping_timeout=None) as websocket:
            # Prepare and send subscription message
            message = {"assets_ids": chunk}
            await websocket.send(json.dumps(message))

            Logan.info(
                f"Sent market subscription message: {message}",
                namespace="websocket_handlers"
            )

            try:
                # Process incoming market data indefinitely
                while True:
                    message = await websocket.recv()
                    json_data = json.loads(message)
                    # Process order book updates and trigger trading as needed
                    await process_market_data(json_data)
            except websockets.ConnectionClosed as e:
                Logan.error(
                    "Market websocket connection closed unexpectedly",
                    namespace="websocket_handlers",
                    exception=e
                )
            except Exception as e:
                Logan.error(
                    "Unexpected error in market websocket connection",
                    namespace="websocket_handlers",
                    exception=e
                )
            finally:
                # Brief delay before attempting to reconnect
                await asyncio.sleep(3)
                gc.collect()


async def connect_user_websocket():
    """
    Connect to Polymarket's user WebSocket API and process order/trade updates.
    
    This function:
    1. Establishes a WebSocket connection to the Polymarket user API
    2. Authenticates using API credentials
    3. Processes incoming order and trade updates for the user
    
    Notes:
        If the connection is lost, the function will exit and the main loop will
        attempt to reconnect after a short delay.
    """
    uri = "wss://ws-subscriptions-clob.polymarket.com/ws/user"

    while True:
        async with websockets.connect(uri, ping_interval=MCNF.WEBSOCKET_PING_INTERVAL, ping_timeout=None) as websocket:
            # Prepare authentication message with API credentials
            message = {
                "type": "user",
                "auth": {
                    "apiKey": global_state.client.client.creds.api_key, 
                    "secret": global_state.client.client.creds.api_secret,  
                    "passphrase": global_state.client.client.creds.api_passphrase
                }
            }

            # Send authentication message
            await websocket.send(json.dumps(message))

            Logan.info(
                "Sent user subscription message",
                namespace="websocket_handlers"
            )

            try:
                # Process incoming user data indefinitely
                while True:
                    message = await websocket.recv()
                    json_data = json.loads(message)
                    # Process trade and order updates
                    await process_user_data(json_data)
            except websockets.ConnectionClosed as e:
                Logan.error(
                    "User websocket connection closed unexpectedly",
                    namespace="websocket_handlers",
                    exception=e
                )
            except Exception as e:
                Logan.error(
                    "Unexpected error in user websocket connection",
                    namespace="websocket_handlers",
                    exception=e
                )
            finally:
                # Brief delay before attempting to reconnect
                await asyncio.sleep(3)
                gc.collect()