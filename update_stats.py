from trading_bot.polymarket_client import PolymarketClient
from poly_stats.account_stats import update_stats_once

import time
from logan import Logan

client = PolymarketClient()

if __name__ == '__main__':
    while True:
        try:
            update_stats_once(client)
        except Exception as e:
            Logan.error(
                "Error updating account stats",
                namespace="update_stats",
                exception=e
            )

        Logan.info(
            "Now sleeping for 3 hours",
            namespace="update_stats"
        )
        time.sleep(60 * 60 * 3) #3 hours