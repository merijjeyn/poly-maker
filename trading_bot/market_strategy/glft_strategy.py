from configuration import TCNF
from trading_bot.global_state import get_active_markets
from trading_bot.market_strategy import MarketStrategy
from trading_bot.market_strategy.ans_strategy import AnSMarketStrategy


class GLFTMarketStrategy(MarketStrategy):
    """
    ChatGPT taught me GLTF strategy and I didn't actually read the paper. And now it seems too simplistic to me. 
    But still it makes sense so its a good starting point. Currently I'm only using it to incorporate rewards.
    """
    
    @classmethod
    def get_buy_sell_amount(cls, position, row, force_sell=False) -> tuple[float, float]:
        return AnSMarketStrategy.get_buy_sell_amount(position, row, force_sell)

    @classmethod
    def get_order_prices(cls, best_bid, best_ask, mid_price, row, token, tick, force_sell=False) -> tuple[float, float]:
        assert mid_price != 0 and mid_price is not None, "Mid price is 0 or None"
        
        bid_price, ask_price = AnSMarketStrategy.get_order_prices(best_bid, best_ask, mid_price, row, token, tick, force_sell)

        # reward_rate = row['rewards_daily_rate']

        # TODO: i don't love this normalized calculation because it is affected by market selection, but it works for now.
        # competition = cls.calculate_normalized_competition_of_market(row)
        # trade_feq = cls.calculate_normalized_trade_feq_of_market(row)
        order_depth = cls.calculate_normalized_order_book_depth_of_market(row)

        bid_price = bid_price - (TCNF.ORDER_BOOK_DEPTH_SKEW_FACTOR / order_depth)
        ask_price = ask_price + (TCNF.ORDER_BOOK_DEPTH_SKEW_FACTOR / order_depth)

        # if competition == 0 or trade_feq == 0:
        #     skew = 0
        # else:
        #     skew = (reward_rate * TCNF.REWARD_SKEW_FACTOR) / competition * math.sqrt(trade_feq)
        #     skew = skew / 100  # convert to USD
        #     skew = min(0.05, skew)
        
        # Only apply reward skew if we end up inside the max reward spread
        # s_half = row['max_spread'] / 100 / 2
        # new_bid_price = bid_price + skew
        # new_ask_price = ask_price - skew
        # inside_max_reward_spread = abs(mid_price - new_bid_price) < s_half and abs(mid_price - new_ask_price) < s_half
        # if inside_max_reward_spread:
        #     bid_price, ask_price = new_bid_price, new_ask_price
        

        # TODO: Implement toxicity filter. if price changed recently, increase spread for a while.

        bid_price, ask_price = cls.apply_safety_guards(bid_price, ask_price, mid_price, tick, best_bid, best_ask, force_sell)
        # Logan.debug(f"result of GLFT: bid_price: {bid_price}, ask_price: {ask_price},  skew: {(TCNF.ORDER_BOOK_DEPTH_SKEW_FACTOR / order_depth)}  force_sell: {force_sell}, best_bid: {best_bid}, best_ask: {best_ask}, mid_price: {mid_price}, token: {token}", namespace="poly_data.market_strategy.glft_strategy")
        return bid_price, ask_price

    @classmethod
    def calculate_normalized_competition_of_market(cls, row):
        depth = row['depth_bids'] + row['depth_asks']

        markets = get_active_markets()
        avg_depth_bids = markets['depth_bids'].mean()
        avg_depth_asks = markets['depth_asks'].mean()
        avg_depth = (avg_depth_bids + avg_depth_asks) / 2

        return depth / avg_depth
    
    @classmethod
    def calculate_normalized_trade_feq_of_market(cls, row):
        trade_feq = row['avg_trades_per_day']

        markets = get_active_markets()
        avg_trade_feq = markets['avg_trades_per_day'].mean()

        return trade_feq / avg_trade_feq
    
    @classmethod
    def calculate_normalized_order_book_depth_of_market(cls, row):
        markets = get_active_markets()
        depth = row['depth_bids'] + row['depth_asks']
        avg_depth = markets['depth_bids'].mean() + markets['depth_asks'].mean()
        return depth / avg_depth
