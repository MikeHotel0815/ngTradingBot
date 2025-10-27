#!/usr/bin/env python3
"""
ML Outcome Updater Worker

Updates ml_predictions table with actual trade outcomes to enable ML learning.

Problem Solved:
- 7,168 ML predictions have no outcome (ml_confidence always 0.0)
- ML models cannot learn without feedback
- This worker closes the feedback loop

How it works:
1. Finds closed trades with signal_id
2. Locates corresponding ml_predictions
3. Updates: actual_outcome, actual_profit, outcome_time, was_correct
4. Enables proper ML training with real-world results

Author: Claude Code
Date: 2025-10-27
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple
from sqlalchemy import and_
from database import ScopedSession
from models import Trade, MLPrediction

logger = logging.getLogger(__name__)


class MLOutcomeUpdater:
    """
    Updates ML predictions with actual trade outcomes
    """

    # Outcome determination thresholds
    MIN_PROFIT_FOR_WIN = 0.01  # Minimum profit to count as win (avoid rounding errors)

    def __init__(self):
        """Initialize ML Outcome Updater"""
        self.last_check_time = None

    def update_outcomes(self, db: Optional[ScopedSession] = None) -> Tuple[int, int]:
        """
        Update ML predictions with outcomes from closed trades

        Args:
            db: Database session (creates new if None)

        Returns:
            Tuple of (updated_count, skipped_count)
        """
        close_db = False
        if db is None:
            db = ScopedSession()
            close_db = True

        try:
            updated_count = 0
            skipped_count = 0

            # Find closed trades with signal_id that don't have outcomes yet
            # Join with ml_predictions to find predictions without outcomes
            closed_trades = db.query(Trade).filter(
                Trade.status == 'closed',
                Trade.signal_id.isnot(None),
                Trade.close_time.isnot(None)
            ).all()

            logger.debug(f"Found {len(closed_trades)} closed trades with signal_id")

            for trade in closed_trades:
                try:
                    # Find ML predictions for this signal
                    predictions = db.query(MLPrediction).filter(
                        MLPrediction.signal_id == trade.signal_id,
                        MLPrediction.actual_outcome.is_(None)  # Only update if not already set
                    ).all()

                    if not predictions:
                        skipped_count += 1
                        continue

                    # Determine outcome
                    outcome = self._determine_outcome(trade)

                    # Update all predictions for this signal
                    for pred in predictions:
                        # Calculate if prediction was correct
                        was_correct = self._was_prediction_correct(
                            pred.decision,
                            trade.profit,
                            pred.prediction_type if hasattr(pred, 'prediction_type') else None
                        )

                        # Update prediction
                        pred.actual_outcome = outcome
                        pred.actual_profit = float(trade.profit) if trade.profit else 0.0
                        pred.outcome_time = trade.close_time
                        pred.was_correct = was_correct

                        # Calculate prediction error if we have predicted value
                        if pred.predicted_value is not None and trade.profit is not None:
                            pred.prediction_error = abs(float(trade.profit) - float(pred.predicted_value))

                        # Link to trade
                        if not pred.trade_id:
                            pred.trade_id = trade.id

                        updated_count += 1

                        logger.debug(
                            f"✅ Updated prediction {pred.id}: "
                            f"signal={trade.signal_id}, outcome={outcome}, "
                            f"profit={trade.profit:.2f}, correct={was_correct}"
                        )

                except Exception as e:
                    logger.error(f"Error updating prediction for trade {trade.id}: {e}")
                    continue

            # Commit all updates
            db.commit()

            if updated_count > 0 or skipped_count > 0:
                logger.info(
                    f"📊 ML Outcome Update: {updated_count} predictions updated, "
                    f"{skipped_count} skipped (already processed or no prediction)"
                )

            self.last_check_time = datetime.utcnow()

            return (updated_count, skipped_count)

        except Exception as e:
            logger.error(f"Error in ML outcome update: {e}", exc_info=True)
            db.rollback()
            return (0, 0)

        finally:
            if close_db:
                db.close()

    def _determine_outcome(self, trade: Trade) -> str:
        """
        Determine trade outcome (win/loss/breakeven)

        Args:
            trade: Trade object

        Returns:
            Outcome string: 'win', 'loss', or 'breakeven'
        """
        if trade.profit is None:
            return 'unknown'

        profit = float(trade.profit)

        if profit >= self.MIN_PROFIT_FOR_WIN:
            return 'win'
        elif profit <= -self.MIN_PROFIT_FOR_WIN:
            return 'loss'
        else:
            return 'breakeven'

    def _was_prediction_correct(
        self,
        decision: str,
        profit: float,
        prediction_type: Optional[str] = None
    ) -> bool:
        """
        Determine if ML prediction was correct

        Args:
            decision: ML decision ('trade', 'no_trade', etc.)
            profit: Actual profit
            prediction_type: Type of prediction (if any)

        Returns:
            True if prediction was correct
        """
        if profit is None or decision is None:
            return False

        profit_value = float(profit)

        # If decision was 'trade', it's correct if trade was profitable
        if decision == 'trade':
            return profit_value >= self.MIN_PROFIT_FOR_WIN

        # If decision was 'no_trade', we can't directly verify
        # (we don't know what would have happened if we traded)
        # So we mark as None/uncertain
        if decision == 'no_trade':
            return False  # Conservative: can't verify no_trade decisions

        return False

    def get_statistics(self, db: Optional[ScopedSession] = None, days: int = 30) -> dict:
        """
        Get ML prediction accuracy statistics

        Args:
            db: Database session
            days: Number of days to analyze

        Returns:
            Dictionary with statistics
        """
        close_db = False
        if db is None:
            db = ScopedSession()
            close_db = True

        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)

            # Total predictions
            total_predictions = db.query(MLPrediction).filter(
                MLPrediction.created_at >= cutoff_date
            ).count()

            # Predictions with outcomes
            with_outcome = db.query(MLPrediction).filter(
                MLPrediction.created_at >= cutoff_date,
                MLPrediction.actual_outcome.isnot(None)
            ).count()

            # Correct predictions
            correct = db.query(MLPrediction).filter(
                MLPrediction.created_at >= cutoff_date,
                MLPrediction.was_correct == True
            ).count()

            # Win/Loss breakdown
            wins = db.query(MLPrediction).filter(
                MLPrediction.created_at >= cutoff_date,
                MLPrediction.actual_outcome == 'win'
            ).count()

            losses = db.query(MLPrediction).filter(
                MLPrediction.created_at >= cutoff_date,
                MLPrediction.actual_outcome == 'loss'
            ).count()

            # Calculate metrics
            outcome_rate = (with_outcome / total_predictions * 100) if total_predictions > 0 else 0
            accuracy = (correct / with_outcome * 100) if with_outcome > 0 else 0
            win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

            return {
                'total_predictions': total_predictions,
                'with_outcome': with_outcome,
                'outcome_rate_pct': round(outcome_rate, 2),
                'correct_predictions': correct,
                'accuracy_pct': round(accuracy, 2),
                'wins': wins,
                'losses': losses,
                'win_rate_pct': round(win_rate, 2),
                'days_analyzed': days,
                'last_check': self.last_check_time.isoformat() if self.last_check_time else None
            }

        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {}

        finally:
            if close_db:
                db.close()

    def backfill_historical_outcomes(self, db: Optional[ScopedSession] = None, days: int = 90) -> int:
        """
        Backfill outcomes for all historical trades (run once to populate existing data)

        Args:
            db: Database session
            days: How many days back to process

        Returns:
            Number of predictions updated
        """
        close_db = False
        if db is None:
            db = ScopedSession()
            close_db = True

        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)

            logger.info(f"🔄 Starting backfill of ML outcomes for last {days} days...")

            # Find all closed trades since cutoff
            trades = db.query(Trade).filter(
                Trade.status == 'closed',
                Trade.signal_id.isnot(None),
                Trade.close_time >= cutoff_date
            ).all()

            logger.info(f"Found {len(trades)} closed trades to backfill")

            updated_count = 0
            batch_size = 100

            for i, trade in enumerate(trades):
                try:
                    # Find predictions without outcomes
                    predictions = db.query(MLPrediction).filter(
                        MLPrediction.signal_id == trade.signal_id,
                        MLPrediction.actual_outcome.is_(None)
                    ).all()

                    for pred in predictions:
                        outcome = self._determine_outcome(trade)
                        was_correct = self._was_prediction_correct(
                            pred.decision,
                            trade.profit,
                            pred.prediction_type if hasattr(pred, 'prediction_type') else None
                        )

                        pred.actual_outcome = outcome
                        pred.actual_profit = float(trade.profit) if trade.profit else 0.0
                        pred.outcome_time = trade.close_time
                        pred.was_correct = was_correct

                        if not pred.trade_id:
                            pred.trade_id = trade.id

                        updated_count += 1

                    # Commit in batches
                    if (i + 1) % batch_size == 0:
                        db.commit()
                        logger.info(f"Backfilled {i + 1}/{len(trades)} trades ({updated_count} predictions)")

                except Exception as e:
                    logger.error(f"Error backfilling trade {trade.id}: {e}")
                    continue

            # Final commit
            db.commit()

            logger.info(f"✅ Backfill complete: {updated_count} predictions updated from {len(trades)} trades")

            return updated_count

        except Exception as e:
            logger.error(f"Error in backfill: {e}", exc_info=True)
            db.rollback()
            return 0

        finally:
            if close_db:
                db.close()


# Singleton instance
_updater = None

def get_ml_outcome_updater() -> MLOutcomeUpdater:
    """Get or create ML outcome updater singleton"""
    global _updater
    if _updater is None:
        _updater = MLOutcomeUpdater()
    return _updater


# CLI interface for manual execution
if __name__ == '__main__':
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='ML Outcome Updater')
    parser.add_argument('--backfill', action='store_true', help='Backfill historical outcomes')
    parser.add_argument('--days', type=int, default=90, help='Days to backfill (default: 90)')
    parser.add_argument('--stats', action='store_true', help='Show statistics only')

    args = parser.parse_args()

    updater = get_ml_outcome_updater()

    if args.stats:
        # Show statistics
        stats = updater.get_statistics(days=args.days)
        print("\n📊 ML Prediction Statistics")
        print("=" * 50)
        for key, value in stats.items():
            print(f"{key:25s}: {value}")

    elif args.backfill:
        # Backfill historical data
        print(f"\n🔄 Backfilling outcomes for last {args.days} days...")
        count = updater.backfill_historical_outcomes(days=args.days)
        print(f"✅ Updated {count} predictions")

        # Show updated statistics
        stats = updater.get_statistics(days=args.days)
        print("\n📊 Updated Statistics:")
        print("=" * 50)
        for key, value in stats.items():
            print(f"{key:25s}: {value}")

    else:
        # Regular update
        updated, skipped = updater.update_outcomes()
        print(f"✅ Updated {updated} predictions, skipped {skipped}")

        # Show statistics
        stats = updater.get_statistics(days=30)
        print("\n📊 Last 30 Days Statistics:")
        print("=" * 50)
        for key, value in stats.items():
            print(f"{key:25s}: {value}")
