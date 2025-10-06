"""
Backtest Scorer Module
Isolated indicator scoring system for backtests
Does NOT affect live scores - completely separate simulation
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class BacktestScorer:
    """
    Isolated indicator scorer for backtests
    Maintains separate scores that DO NOT affect live system
    """

    def __init__(self, symbol: str, timeframe: str):
        """
        Initialize Backtest Scorer

        Args:
            symbol: Trading symbol (e.g., EURUSD)
            timeframe: Timeframe (M5, M15, H1, H4, D1)
        """
        self.symbol = symbol
        self.timeframe = timeframe

        # In-memory score storage (isolated from live DB)
        self.scores: Dict[str, Dict] = {}

        logger.info(f"📊 BacktestScorer initialized for {symbol} {timeframe} (isolated mode)")

    def get_indicator_weight(self, indicator_name: str) -> float:
        """
        Get weight for an indicator (0.0 - 1.0) based on its score

        Args:
            indicator_name: Name of the indicator (e.g., RSI, MACD)

        Returns:
            Weight value (0.0 - 1.0)
        """
        # Initialize if not exists
        if indicator_name not in self.scores:
            self.scores[indicator_name] = {
                'score': 50.0,  # Start neutral
                'total_signals': 0,
                'successful_signals': 0,
                'failed_signals': 0,
                'total_profit': 0.0,
                'avg_profit': 0.0,
                'best_profit': 0.0,
                'worst_loss': 0.0
            }

        score_obj = self.scores[indicator_name]

        # Convert score (0-100) to weight (0.0-1.0)
        # Minimum weight is 0.3 (even at score 0) to allow recovery
        # Maximum weight is 1.0 (at score 100)
        weight = 0.3 + (score_obj['score'] / 100) * 0.7

        return weight

    def update_score(self, indicator_name: str, was_profitable: bool, profit: float):
        """
        Update indicator score after trade closes (in backtest)

        Args:
            indicator_name: Name of the indicator
            was_profitable: Whether the trade was profitable
            profit: Profit/loss amount
        """
        # Initialize if not exists
        if indicator_name not in self.scores:
            self.get_indicator_weight(indicator_name)  # Creates default

        score_obj = self.scores[indicator_name]
        old_score = score_obj['score']

        # Update stats
        score_obj['total_signals'] += 1
        score_obj['total_profit'] += profit

        if was_profitable:
            score_obj['successful_signals'] += 1
            if profit > score_obj['best_profit']:
                score_obj['best_profit'] = profit
        else:
            score_obj['failed_signals'] += 1
            if profit < score_obj['worst_loss']:
                score_obj['worst_loss'] = profit

        # Calculate new score (same formula as live)
        total = score_obj['total_signals']
        if total > 0:
            # Win rate (0-100)
            win_rate = (score_obj['successful_signals'] / total) * 100

            # Average profit
            score_obj['avg_profit'] = score_obj['total_profit'] / total

            # Profit factor: avg_profit normalized to 0-100 scale
            # Assuming max $100 avg profit = 100 score
            profit_factor = min(100, max(0, (score_obj['avg_profit'] / 100) * 100 + 50))

            # Score = 70% win rate + 30% profit factor
            score_obj['score'] = (win_rate * 0.7) + (profit_factor * 0.3)
            score_obj['score'] = max(0, min(100, score_obj['score']))  # Clamp to 0-100

        logger.debug(
            f"📊 [BACKTEST] Updated {indicator_name} score for {self.symbol} {self.timeframe}: "
            f"{old_score:.1f}% → {score_obj['score']:.1f}% "
            f"({'✅ WIN' if was_profitable else '❌ LOSS'} ${profit:+.2f}) "
            f"[{score_obj['successful_signals']}/{score_obj['total_signals']} signals]"
        )

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

    def get_all_scores(self) -> Dict[str, Dict]:
        """
        Get all indicator scores

        Returns:
            Dict mapping indicator names to their score dicts
        """
        return self.scores.copy()

    def get_score_summary(self) -> List[Dict]:
        """
        Get summary of all scores for export/analysis

        Returns:
            List of score dicts sorted by score descending
        """
        summary = []
        for indicator_name, score_obj in self.scores.items():
            summary.append({
                'indicator_name': indicator_name,
                'score': round(score_obj['score'], 2),
                'weight': round(self.get_indicator_weight(indicator_name), 2),
                'total_signals': score_obj['total_signals'],
                'successful_signals': score_obj['successful_signals'],
                'failed_signals': score_obj['failed_signals'],
                'win_rate': round((score_obj['successful_signals'] / score_obj['total_signals'] * 100)
                                  if score_obj['total_signals'] > 0 else 0, 2),
                'total_profit': round(score_obj['total_profit'], 2),
                'avg_profit': round(score_obj['avg_profit'], 2),
                'best_profit': round(score_obj['best_profit'], 2),
                'worst_loss': round(score_obj['worst_loss'], 2)
            })

        # Sort by score descending
        summary.sort(key=lambda x: x['score'], reverse=True)

        return summary

    def export_recommended_scores(self) -> Dict[str, float]:
        """
        Export recommended initial scores for live system

        Returns:
            Dict mapping indicator names to recommended scores
        """
        recommended = {}

        for indicator_name, score_obj in self.scores.items():
            # Only recommend if we have enough data (min 5 signals)
            if score_obj['total_signals'] >= 5:
                recommended[indicator_name] = round(score_obj['score'], 2)

        logger.info(
            f"📊 Exported {len(recommended)} recommended scores for {self.symbol} {self.timeframe} "
            f"(from {len(self.scores)} total indicators)"
        )

        return recommended

    def get_score_evolution(self) -> Dict[str, List]:
        """
        Get score evolution over time (for charting)
        Note: Would need to track history during backtest
        This is a placeholder for future enhancement
        """
        # TODO: Track score history during backtest
        # Return snapshots every N trades
        return {}
