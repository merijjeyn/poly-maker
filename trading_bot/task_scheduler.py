import asyncio
import time
from typing import Awaitable, Callable, Hashable

from logan import Logan
from opentelemetry.metrics import get_meter

from trading_bot.orders_in_flight import get_orders_in_flight

meter = get_meter("task_scheduler")
task_in_flight_counter = meter.create_up_down_counter("task_in_flight_counter", description="Number of tasks in flight")
task_latency_histogram = meter.create_histogram("task_latency_histogram", description="Latency of tasks", unit="ms")
task_schedule_counter = meter.create_up_down_counter("task_schedule_counter", description="Number of tasks scheduled")

class TaskScheduler:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._inflight: set[Hashable] = set()

    async def schedule_task(self, market: str, task: Callable[[str], Awaitable[None]]) -> None:
        if market in self._inflight:
            return
            
        async with self._lock:
            orders_in_flight = get_orders_in_flight(market)
            if len(orders_in_flight) > 0:
                return
            
            self._inflight.add(market)
            task_in_flight_counter.add(1)

            async def run_task():
                try:
                    task_schedule_counter.add(1)
                    start = time.perf_counter()
                    await task(market)
                    end = time.perf_counter()
                    task_latency_histogram.record(end - start)
                except Exception as e:
                    Logan.error(f"Error running task for market {market}", namespace="task_scheduler", exception=e)
                finally:
                    self._inflight.remove(market)
                    task_in_flight_counter.add(-1)

            asyncio.create_task(run_task())

Scheduler = TaskScheduler()