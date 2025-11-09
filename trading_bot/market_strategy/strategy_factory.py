"""
StrategyFactory manages the global market strategy instance used throughout the application.
"""

from enum import Enum
from typing import Optional

from trading_bot.market_strategy import MarketStrategy
from trading_bot.market_strategy.ans_derisked_strategy import ANSDeriskedMarketStrategy
from trading_bot.market_strategy.ans_strategy import AnSMarketStrategy
from trading_bot.market_strategy.glft_strategy import GLFTMarketStrategy


class StrategyType(str, Enum):
    ANS = "ans"
    GLFT = "glft"
    ANS_DERISKED = "ans_derisked"

class StrategyFactory:
    _instance: Optional[MarketStrategy] = None
    
    # Available strategies mapping
    _STRATEGIES = {
        StrategyType.ANS: AnSMarketStrategy,
        StrategyType.GLFT: GLFTMarketStrategy,
        StrategyType.ANS_DERISKED: ANSDeriskedMarketStrategy
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

