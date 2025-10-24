import asyncio
from typing import Any, Awaitable, Callable, Hashable

from logan import Logan

from trading_bot.orders_in_flight import get_orders_in_flight


class TaskScheduler:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._inflight: set[Hashable] = set()

    async def schedule_task(self, market: str, task: Callable[[], Awaitable[None]]) -> None:
        async with self._lock:
            if market in self._inflight:
                return
            
            orders_in_flight = get_orders_in_flight(market)
            if len(orders_in_flight) > 0:
                return
            
            self._inflight.add(market)

            async def run_task():
                try:
                    await task()
                except Exception as e:
                    Logan.error(f"Error running task for market {market}", namespace="task_scheduler", exception=e)
                finally:
                    self._inflight.remove(market)

            asyncio.create_task(run_task())

Scheduler = TaskScheduler()