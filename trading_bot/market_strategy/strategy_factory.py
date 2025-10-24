"""
StrategyFactory manages the global market strategy instance used throughout the application.
"""

from enum import Enum

from trading_bot.market_strategy import MarketStrategy
from trading_bot.market_strategy.ans_strategy import AnSMarketStrategy
from trading_bot.market_strategy.glft_strategy import GLFTMarketStrategy


class StrategyType(str, Enum):
    ANS = "ans"
    GLFT = "glft"


class StrategyFactory:
    _instance: MarketStrategy = None
    
    # Available strategies mapping
    _STRATEGIES = {
        StrategyType.ANS: AnSMarketStrategy,
        StrategyType.GLFT: GLFTMarketStrategy
    }
    
    @classmethod
    def init(cls, strategy: StrategyType) -> None:
        cls._instance = cls._STRATEGIES[strategy]
    
    @classmethod
    def get(cls) -> MarketStrategy:
        if cls._instance is None:
            raise RuntimeError(
                "Strategy has not been initialized. Call StrategyFactory.init() first."
            )
        return cls._instance

