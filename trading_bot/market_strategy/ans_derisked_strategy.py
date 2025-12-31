from typing import Optional

from growthbook import GrowthBook

from configuration import TCNF
from trading_bot.market_strategy import MarketStrategy
from trading_bot.market_strategy.ans_strategy import AnSMarketStrategy
from trading_bot.order_books import OrderBooks


class ANSDeriskedMarketStrategy(MarketStrategy):
    """
    Applying ANS strategy with derisking by the order book depth, and post fill shock protection.
    """
    
    @classmethod
    def get_buy_sell_amount(cls, position, row, gb: Optional[GrowthBook] = None, force_sell=False) -> tuple[float, float]:
        return AnSMarketStrategy.get_buy_sell_amount(position, row, gb, force_sell)

    @classmethod
    def get_order_prices(cls, best_bid, best_ask, mid_price, row, token, tick, gb: Optional[GrowthBook] = None, force_sell=False) -> tuple[float, float]:
        assert mid_price != 0 and mid_price is not None, "Mid price is 0 or None"

        bid_price, ask_price = AnSMarketStrategy.get_order_prices(best_bid, best_ask, mid_price, row, token, tick, gb, force_sell)

        depth_bid_addon, depth_ask_addon = cls.calculate_book_depth_addon(token, row, gb)
        bid_price = bid_price - depth_bid_addon
        ask_price = ask_price + depth_ask_addon
        # Logan.debug(f"depth_bid_addon: {depth_bid_addon}, depth_ask_addon: {depth_ask_addon}, bid_price: {bid_price}, ask_price: {ask_price}, mid_price: {mid_price}", namespace="trading_bot.market_strategy.ans_derisked_strategy")

        bid_price, ask_price = cls.apply_safety_guards(bid_price, ask_price, mid_price, tick, best_bid, best_ask, force_sell)
        return bid_price, ask_price
    
    @classmethod
    def calculate_book_depth_addon(cls, token, row, gb: Optional[GrowthBook] = None) -> tuple[float, float]:
        order_book = OrderBooks.get(token)
        depth_bids, depth_asks = order_book.get_market_depth()

        avg_trade_vol = row['avg_trades_per_hour'] * row['avg_trade_size']

        if depth_bids == 0 or depth_asks == 0:
            return 0, 0

        skew_factor = TCNF.get_order_book_depth_skew_factor_with_gb(gb)
        depth_bid_addon = skew_factor * avg_trade_vol / depth_bids
        depth_ask_addon = skew_factor * avg_trade_vol / depth_asks
        return depth_bid_addon, depth_ask_addon