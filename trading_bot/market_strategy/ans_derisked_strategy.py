from configuration import TCNF
from trading_bot.market_strategy import MarketStrategy
from trading_bot.market_strategy.ans_strategy import AnSMarketStrategy


class ANSDeriskedMarketStrategy(MarketStrategy):
    """
    Applying ANS strategy with derisking by the order book depth, and post fill shock protection.
    """
    
    @classmethod
    def get_buy_sell_amount(cls, position, row, force_sell=False) -> tuple[float, float]:
        return AnSMarketStrategy.get_buy_sell_amount(position, row, force_sell)

    @classmethod
    def get_order_prices(cls, best_bid, best_ask, mid_price, row, token, tick, force_sell=False) -> tuple[float, float]:
        assert mid_price != 0 and mid_price is not None, "Mid price is 0 or None"
        
        bid_price, ask_price = AnSMarketStrategy.get_order_prices(best_bid, best_ask, mid_price, row, token, tick, force_sell)

        depth_bid_addon, depth_ask_addon = cls.calculate_book_depth_addon(token, row)
        bid_price = bid_price - depth_bid_addon
        ask_price = ask_price + depth_ask_addon
        # Logan.debug(f"depth_bid_addon: {depth_bid_addon}, depth_ask_addon: {depth_ask_addon}, bid_price: {bid_price}, ask_price: {ask_price}, mid_price: {mid_price}", namespace="trading_bot.market_strategy.ans_derisked_strategy")

        bid_price, ask_price = cls.apply_safety_guards(bid_price, ask_price, mid_price, tick, best_bid, best_ask, force_sell)
        return bid_price, ask_price
    
    @classmethod
    def calculate_book_depth_addon(cls, token, row) -> tuple[float, float]:
        if token == str(row['token1']):
            depth_bids = row['depth_bids']
            depth_asks = row['depth_asks']
        elif token == str(row['token2']):
            depth_bids = row['depth_asks']
            depth_asks = row['depth_bids']
        else:
            raise ValueError(f"Token {token} is not in the row")

        avg_trade_vol = row['avg_trades_per_hour'] * row['avg_trade_size']

        if depth_bids == 0 or depth_asks == 0:
            return 0, 0

        depth_bid_addon = TCNF.ORDER_BOOK_DEPTH_SKEW_FACTOR * avg_trade_vol / depth_bids
        depth_ask_addon = TCNF.ORDER_BOOK_DEPTH_SKEW_FACTOR * avg_trade_vol / depth_asks
        
        return depth_bid_addon, depth_ask_addon