"""
Indicator Scorer Module
Manages symbol-specific indicator performance scores
"""

import logging
from typing import Dict, List, Optional
from database import ScopedSession
from models import IndicatorScore

logger = logging.getLogger(__name__)


class IndicatorScorer:
    """
    Manages indicator scores for symbol-specific performance tracking
    """

    def __init__(self, account_id: int, symbol: str, timeframe: str):
        """
        Initialize Indicator Scorer

        Args:
            account_id: Account ID
            symbol: Trading symbol (e.g., EURUSD)
            timeframe: Timeframe (M5, M15, H1, H4, D1)
        """
        self.account_id = account_id
        self.symbol = symbol
        self.timeframe = timeframe

    def get_indicator_weight(self, indicator_name: str) -> float:
        """
        Get weight for an indicator (0.0 - 1.0) based on its score

        Args:
            indicator_name: Name of the indicator (e.g., RSI, MACD)

        Returns:
            Weight value (0.0 - 1.0)
        """
        db = ScopedSession()
        try:
            score_obj = IndicatorScore.get_or_create(
                db, self.account_id, self.symbol, self.timeframe, indicator_name
            )

            # Convert score (0-100) to weight (0.0-1.0)
            # Minimum weight is 0.3 (even at score 0) to allow recovery
            # Maximum weight is 1.0 (at score 100)
            weight = 0.3 + (float(score_obj.score) / 100) * 0.7

            logger.debug(
                f"Indicator weight: {indicator_name} for {self.symbol} {self.timeframe}: "
                f"{float(score_obj.score):.1f}% → weight {weight:.2f} "
                f"({score_obj.successful_signals}/{score_obj.total_signals} signals)"
            )

            return weight

        except Exception as e:
            logger.error(f"Error getting indicator weight: {e}")
            return 0.5  # Default neutral weight
        finally:
            db.close()

    def get_all_weights(self, indicator_names: List[str]) -> Dict[str, float]:
        """
        Get weights for multiple indicators at once

        Args:
            indicator_names: List of indicator names

        Returns:
            Dict mapping indicator names to weights
        """
        weights = {}
        for indicator_name in indicator_names:
            weights[indicator_name] = self.get_indicator_weight(indicator_name)

        return weights

    def update_score(self, indicator_name: str, was_profitable: bool, profit: float):
        """
        Update indicator score after trade closes

        Args:
            indicator_name: Name of the indicator
            was_profitable: Whether the trade was profitable
            profit: Profit/loss amount
        """
        db = ScopedSession()
        try:
            score_obj = IndicatorScore.get_or_create(
                db, self.account_id, self.symbol, self.timeframe, indicator_name
            )

            old_score = score_obj.score
            score_obj.update_score(was_profitable, profit)
            db.commit()

            logger.info(
                f"📊 Updated {indicator_name} score for {self.symbol} {self.timeframe}: "
                f"{old_score:.1f}% → {score_obj.score:.1f}% "
                f"({'✅ WIN' if was_profitable else '❌ LOSS'} ${profit:+.2f}) "
                f"[{score_obj.successful_signals}/{score_obj.total_signals} signals]"
            )

        except Exception as e:
            logger.error(f"Error updating indicator score: {e}")
            db.rollback()
        finally:
            db.close()

    def update_multiple_scores(self, indicators_used: Dict[str, any], was_profitable: bool, profit: float):
        """
        Update scores for multiple indicators at once

        Args:
            indicators_used: Dict of indicators that generated the signal
            was_profitable: Whether the trade was profitable
            profit: Profit/loss amount
        """
        for indicator_name in indicators_used.keys():
            self.update_score(indicator_name, was_profitable, profit)

    def get_top_indicators(self, limit: int = 5) -> List[Dict]:
        """
        Get top performing indicators for this symbol/timeframe

        Args:
            limit: Maximum number of indicators to return

        Returns:
            List of top indicator dicts with name, score, and stats
        """
        db = ScopedSession()
        try:
            top_scores = IndicatorScore.get_top_indicators(
                db, self.account_id, self.symbol, self.timeframe, limit
            )

            results = []
            for score_obj in top_scores:
                results.append({
                    'indicator_name': score_obj.indicator_name,
                    'score': float(score_obj.score),
                    'total_signals': score_obj.total_signals,
                    'successful_signals': score_obj.successful_signals,
                    'win_rate': (score_obj.successful_signals / score_obj.total_signals * 100)
                                if score_obj.total_signals > 0 else 0,
                    'avg_profit': float(score_obj.avg_profit) if score_obj.avg_profit else 0.0
                })

            return results

        except Exception as e:
            logger.error(f"Error getting top indicators: {e}")
            return []
        finally:
            db.close()

    def get_all_scores(self) -> List[Dict]:
        """
        Get all indicator scores for this symbol/timeframe

        Returns:
            List of all indicator score dicts
        """
        db = ScopedSession()
        try:
            scores = IndicatorScore.get_symbol_scores(
                db, self.account_id, self.symbol, self.timeframe
            )

            results = []
            for score_obj in scores:
                results.append({
                    'indicator_name': score_obj.indicator_name,
                    'score': float(score_obj.score),
                    'weight': self.get_indicator_weight(score_obj.indicator_name),
                    'total_signals': score_obj.total_signals,
                    'successful_signals': score_obj.successful_signals,
                    'failed_signals': score_obj.failed_signals,
                    'win_rate': (score_obj.successful_signals / score_obj.total_signals * 100)
                                if score_obj.total_signals > 0 else 0,
                    'avg_profit': float(score_obj.avg_profit) if score_obj.avg_profit else 0.0,
                    'total_profit': float(score_obj.total_profit) if score_obj.total_profit else 0.0,
                    'best_profit': float(score_obj.best_profit) if score_obj.best_profit else 0.0,
                    'worst_loss': float(score_obj.worst_loss) if score_obj.worst_loss else 0.0,
                    'last_updated': score_obj.last_updated.isoformat() if score_obj.last_updated else None
                })

            return results

        except Exception as e:
            logger.error(f"Error getting all scores: {e}")
            return []
        finally:
            db.close()
