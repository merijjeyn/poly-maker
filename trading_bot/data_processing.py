from opentelemetry import trace
from opentelemetry.metrics import get_meter
from sortedcontainers import SortedDict
import trading_bot.global_state as global_state

from trading_bot.orders_in_flight import clear_order_in_flight
from trading_bot.task_scheduler import Scheduler
from trading_bot.trading import perform_trade
import time     
import asyncio
from trading_bot.data_utils import set_position, set_order, update_positions
from logan import Logan

tracer = trace.get_tracer("data_processing")
meter = get_meter("data_processing")
performing_counter = meter.create_up_down_counter("performing_counter", description="Number of trades currently being performed")

def sync_order_book_data_for_reverse_token(updated_token: str):
    reverse_token = global_state.REVERSE_TOKENS[updated_token]
    global_state.order_book_data[reverse_token] = {
        'bids': SortedDict(),
        'asks': SortedDict()
    }

    global_state.order_book_data[reverse_token]['asks'].update({1 - price: size for price, size in global_state.order_book_data[updated_token]['bids'].items()})
    global_state.order_book_data[reverse_token]['bids'].update({1 - price: size for price, size in global_state.order_book_data[updated_token]['asks'].items()})

def process_book_data(token: str, json_data):
    global_state.order_book_data[token] = {
        'bids': SortedDict(),
        'asks': SortedDict()
    }

    global_state.order_book_data[token]['bids'].update({float(entry['price']): float(entry['size']) for entry in json_data['bids']})
    global_state.order_book_data[token]['asks'].update({float(entry['price']): float(entry['size']) for entry in json_data['asks']})

    sync_order_book_data_for_reverse_token(token)

def process_price_change(token: str, side, price_level, new_size):
    if side == 'bids':
        book = global_state.order_book_data[token]['bids']
    else:
        book = global_state.order_book_data[token]['asks']

    if new_size == 0:
        if price_level in book:
            del book[price_level]
    else:
        book[price_level] = new_size
    
    sync_order_book_data_for_reverse_token(token)

async def process_market_data(json_datas, trade=True):
    with tracer.start_as_current_span("process_market_data") as span:
        if isinstance(json_datas, dict):
            json_datas = [json_datas]
        elif not isinstance(json_datas, list):
            Logan.error(f"Expected dict or list of dicts, got: {type(json_datas)}", namespace="poly_data.data_processing")
            return

        for json_data in json_datas:
            with tracer.start_as_current_span("process_market_datum") as span:
                event_type = json_data['event_type']
                market = json_data['market']

                span.set_attribute("event_type", event_type)
                span.set_attribute("market", market)

                if event_type == 'book':
                    token = str(json_data['asset_id'])
                    span.set_attribute("token", token)
                    process_book_data(token, json_data)

                    if trade:
                        span.add_event("schedule_trade")
                        await Scheduler.schedule_task(market, perform_trade)
                        
                        
                elif event_type == 'price_change':
                    token, side, price_level, new_size = None, None, None, None
                    for data in json_data['price_changes']:
                        token = str(data['asset_id'])
                        side = 'bids' if data['side'] == 'BUY' else 'asks'
                        price_level = float(data['price'])
                        new_size = float(data['size'])
                        process_price_change(token, side, price_level, new_size)


                    span.set_attribute("token", token if token else "None")
                    span.set_attribute("side", side if side else "None")
                    span.set_attribute("price_level", price_level if price_level else "None")
                    span.set_attribute("new_size", new_size if new_size else "None")

                    if trade:
                        span.add_event("schedule_trade")
                        await Scheduler.schedule_task(market, perform_trade)

def add_to_performing(col, id):
    performing_counter.add(1)
    if col not in global_state.performing:
        global_state.performing[col] = set()
    
    if col not in global_state.performing_timestamps:
        global_state.performing_timestamps[col] = {}

    # Add the trade ID and track its timestamp
    global_state.performing[col].add(id)
    global_state.performing_timestamps[col][id] = time.time()

def remove_from_performing(col, id):
    performing_counter.add(-1)
    if col in global_state.performing:
        global_state.performing[col].discard(id)

    if col in global_state.performing_timestamps:
        global_state.performing_timestamps[col].pop(id, None)

async def process_user_data(rows):
    with tracer.start_as_current_span("process_user_data") as span:
        if isinstance(rows, dict):
            rows = [rows]
        elif not isinstance(rows, list):
            Logan.error(f"Expected dict or list of dicts, got: {type(rows)}", namespace="poly_data.data_processing")
            return

        for row in rows:
            with tracer.start_as_current_span("process_user_datum") as span:
                market = row['market']
                span.set_attribute("market", market)

                side = row['side'].lower()
                token = row['asset_id']
                span.set_attribute("token", token)
                span.set_attribute("event_type", row['event_type'])

                    
                if token in global_state.REVERSE_TOKENS:     
                    col = token + "_" + side

                    if row['event_type'] == 'trade':
                        size = 0
                        price = 0
                        maker_outcome = ""
                        taker_outcome = row['outcome']

                        is_user_maker = False
                        for maker_order in row['maker_orders']:
                            if maker_order['maker_address'].lower() == global_state.client.browser_wallet.lower():
                                Logan.info(
                                    "User is maker",
                                    namespace="poly_data.data_processing"
                                )
                                size = float(maker_order['matched_amount'])
                                price = float(maker_order['price'])
                                
                                is_user_maker = True
                                maker_outcome = maker_order['outcome'] #this is curious

                                if maker_outcome == taker_outcome:
                                    side = 'buy' if side == 'sell' else 'sell' #need to reverse as we reverse token too
                                else:
                                    token = global_state.REVERSE_TOKENS[token]
                        
                        if not is_user_maker:
                            size = float(row['size'])
                            price = float(row['price'])
                            Logan.info(
                                "User is taker",
                                namespace="poly_data.data_processing"
                            )

                        span.set_attribute("market", row['market'])
                        span.set_attribute("id", row['id'])
                        span.set_attribute("side", side)
                        span.set_attribute("size", size)
                        span.set_attribute("price", price)
                        span.set_attribute("status", row['status'])
                        span.set_attribute("maker_outcome", maker_outcome)
                        span.set_attribute("taker_outcome", taker_outcome)

                        Logan.info(
                            f"TRADE EVENT FOR: {row['market']}, ID: {row['id']}, STATUS: {row['status']}, SIDE: {row['side']}, MAKER OUTCOME: {maker_outcome}, TAKER OUTCOME: {taker_outcome}, PROCESSED SIDE: {side}, SIZE: {size}",
                            namespace="poly_data.data_processing"
                        ) 

                        if row['status'] == 'FAILED':
                            Logan.error(
                                f"Trade failed for {token}, decreasing",
                                namespace="poly_data.data_processing"
                            )
                            asyncio.create_task(asyncio.sleep(2))
                            update_positions()
                        elif row['status'] == 'CONFIRMED':
                            remove_from_performing(col, row['id'])
                            Logan.info(
                                f"Confirmed. Performing is {len(global_state.performing[col])}",
                                namespace="poly_data.data_processing"
                            )
                            span.add_event("schedule_task")
                            await Scheduler.schedule_task(market, perform_trade)
                        elif row['status'] == 'MATCHED':
                            add_to_performing(col, row['id'])

                            Logan.info(
                                f"Matched. Performing is {len(global_state.performing[col])}",
                                namespace="poly_data.data_processing"
                            )
                            set_position(token, side, size, price)
                            Logan.info(
                                f"Position after matching is {global_state.positions[str(token)]}",
                                namespace="poly_data.data_processing"
                            )
                            span.add_event("schedule_task")
                            await Scheduler.schedule_task(market, perform_trade)
                        elif row['status'] == 'MINED':
                            remove_from_performing(col, row['id'])

                    elif row['event_type'] == 'order':
                        Logan.info(
                            f"ORDER EVENT FOR: {row['market']}, STATUS: {row['status']}, TYPE: {row['type']}, SIDE: {side}, ORIGINAL SIZE: {row['original_size']}, SIZE MATCHED: {row['size_matched']}",
                            namespace="poly_data.data_processing"
                        )
                        
                        try: 
                            order_size = global_state.orders[token][side]['size'] # size of existing orders
                        except Exception:
                            order_size = 0

                        if row['type'] == 'PLACEMENT':
                            order_size += float(row['original_size'])
                        elif row['type'] == 'UPDATE': 
                            order_size -= float(row['size_matched'])
                        elif row['type'] == 'CANCELLATION':
                            order_size -= float(row['original_size'])
                        
                        order_size = max(order_size, 0)

                        span.set_attribute("original_size", row['original_size'])
                        span.set_attribute("size_matched", row['size_matched'])
                        span.set_attribute("order_size_after_processing", order_size)
                        span.set_attribute("market", row['market'])
                        span.set_attribute("side", side)
                        span.set_attribute("token", token)
                        span.set_attribute("id", row['id'])
                        span.set_attribute("type", row['type'])
                        span.set_attribute("price", row['price'])

                        set_order(token, side, order_size, row['price'])
                        clear_order_in_flight(row['id'])
                        
                        if (row['type'] != 'PLACEMENT'): 
                            span.add_event("schedule_task")
                            await Scheduler.schedule_task(market, perform_trade)

