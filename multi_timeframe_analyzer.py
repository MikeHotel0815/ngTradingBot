"""
Multi-Timeframe Conflict Detection

Detects when lower timeframe signals conflict with higher timeframe signals.
Reduces confidence when trading against the higher timeframe trend.

Trading Principle: "Trade with the trend of the higher timeframe"
"""

import logging
from typing import Dict, Optional, List, Tuple
from sqlalchemy.orm import Session
from models import TradingSignal
from database import ScopedSession

logger = logging.getLogger(__name__)


class MultiTimeframeAnalyzer:
    """Analyzes multi-timeframe signal alignment"""

    # Timeframe hierarchy (lower → higher)
    TIMEFRAME_HIERARCHY = {
        'M1': 0,
        'M5': 1,
        'M15': 2,
        'M30': 3,
        'H1': 4,
        'H4': 5,
        'D1': 6,
        'W1': 7,
        'MN1': 8
    }

    # Confidence penalties for conflicts (ENHANCED)
    # When higher TF has strong confidence, strongly penalize conflicting lower TF
    CONFLICT_PENALTY_ADJACENT = 20.0  # H1 vs H4 = -20% (was -10%)
    CONFLICT_PENALTY_FAR = 30.0       # H1 vs D1 = -30% (was -15%)
    CONFLICT_BONUS_ALIGNED = 10.0     # All aligned = +10% (was +5%)

    @classmethod
    def get_timeframe_rank(cls, timeframe: str) -> int:
        """Get numeric rank of timeframe (lower = shorter period)"""
        return cls.TIMEFRAME_HIERARCHY.get(timeframe, -1)

    @classmethod
    def is_higher_timeframe(cls, tf1: str, tf2: str) -> bool:
        """Check if tf1 is higher (longer period) than tf2"""
        return cls.get_timeframe_rank(tf1) > cls.get_timeframe_rank(tf2)

    @classmethod
    def get_timeframe_distance(cls, tf1: str, tf2: str) -> int:
        """Calculate distance between timeframes (in hierarchy steps)"""
        rank1 = cls.get_timeframe_rank(tf1)
        rank2 = cls.get_timeframe_rank(tf2)
        if rank1 == -1 or rank2 == -1:
            return 0
        return abs(rank1 - rank2)

    @classmethod
    def check_conflict(
        cls,
        current_signal_type: str,
        current_timeframe: str,
        symbol: str,
        account_id: int,
        db: Optional[Session] = None
    ) -> Dict:
        """
        Check if current signal conflicts with higher timeframe signals.

        Args:
            current_signal_type: 'BUY' or 'SELL'
            current_timeframe: Timeframe of current signal (e.g., 'H1')
            symbol: Trading symbol
            account_id: Account ID
            db: Database session (optional)

        Returns:
            Dict with:
                - has_conflict: bool
                - confidence_adjustment: float (penalty or bonus)
                - conflicting_signals: List of conflicting signals
                - aligned_signals: List of aligned signals
                - reason: str (explanation)
        """
        close_db = False
        if db is None:
            db = ScopedSession()
            close_db = True

        try:
            result = {
                'has_conflict': False,
                'confidence_adjustment': 0.0,
                'conflicting_signals': [],
                'aligned_signals': [],
                'reason': ''
            }

            current_rank = cls.get_timeframe_rank(current_timeframe)
            if current_rank == -1:
                return result

            # Get active signals for this symbol (all timeframes)
            # Note: Signals are now global (no account_id)
            active_signals = db.query(TradingSignal).filter(
                TradingSignal.symbol == symbol,
                TradingSignal.status == 'active'
            ).all()

            if not active_signals:
                return result

            conflicts = []
            aligned = []

            for signal in active_signals:
                # Skip same timeframe
                if signal.timeframe == current_timeframe:
                    continue

                signal_rank = cls.get_timeframe_rank(signal.timeframe)
                if signal_rank == -1:
                    continue

                # Only check HIGHER timeframes (ignore lower ones)
                if signal_rank <= current_rank:
                    continue

                # Check if signals align or conflict
                if signal.signal_type == current_signal_type:
                    # Aligned with higher timeframe
                    aligned.append({
                        'timeframe': signal.timeframe,
                        'signal_type': signal.signal_type,
                        'confidence': float(signal.confidence or 0),
                        'distance': signal_rank - current_rank
                    })
                else:
                    # Conflicting with higher timeframe
                    conflicts.append({
                        'timeframe': signal.timeframe,
                        'signal_type': signal.signal_type,
                        'confidence': float(signal.confidence or 0),
                        'distance': signal_rank - current_rank
                    })

            # Calculate confidence adjustment
            if conflicts:
                result['has_conflict'] = True
                result['conflicting_signals'] = conflicts

                # Calculate penalty based on conflicts
                total_penalty = 0.0
                conflict_reasons = []

                for conflict in conflicts:
                    # Adjacent timeframe (H1 vs H4) = smaller penalty
                    if conflict['distance'] == 1:
                        penalty = cls.CONFLICT_PENALTY_ADJACENT
                    else:
                        # Far timeframe (H1 vs D1) = larger penalty
                        penalty = cls.CONFLICT_PENALTY_FAR

                    # Weight penalty by higher TF confidence
                    weighted_penalty = penalty * (conflict['confidence'] / 100.0)
                    total_penalty += weighted_penalty

                    conflict_reasons.append(
                        f"{conflict['timeframe']} {conflict['signal_type']} "
                        f"({conflict['confidence']:.0f}%)"
                    )

                result['confidence_adjustment'] = -min(total_penalty, 40.0)  # Max -40% (was -25%)
                result['reason'] = (
                    f"Conflicts with higher timeframes: {', '.join(conflict_reasons)}"
                )

                logger.warning(
                    f"⚠️ Multi-TF Conflict: {symbol} {current_timeframe} {current_signal_type} "
                    f"conflicts with {conflict_reasons} → Penalty: {result['confidence_adjustment']:.1f}%"
                )

            elif aligned:
                result['aligned_signals'] = aligned

                # Bonus for alignment (max +10%, was +5%)
                bonus = min(cls.CONFLICT_BONUS_ALIGNED, len(aligned) * 5.0)
                result['confidence_adjustment'] = bonus
                result['reason'] = (
                    f"Aligned with {len(aligned)} higher timeframe(s)"
                )

                logger.info(
                    f"✅ Multi-TF Aligned: {symbol} {current_timeframe} {current_signal_type} "
                    f"aligned with {len(aligned)} higher TF(s) → Bonus: +{bonus:.1f}%"
                )

            return result

        except Exception as e:
            logger.error(f"Error checking multi-timeframe conflict: {e}", exc_info=True)
            return {
                'has_conflict': False,
                'confidence_adjustment': 0.0,
                'conflicting_signals': [],
                'aligned_signals': [],
                'reason': ''
            }
        finally:
            if close_db:
                db.close()

    @classmethod
    def get_multi_timeframe_summary(
        cls,
        symbol: str,
        account_id: int,
        db: Optional[Session] = None
    ) -> Dict:
        """
        Get summary of all active signals across timeframes for a symbol.

        Returns:
            Dict with signals grouped by timeframe and direction
        """
        close_db = False
        if db is None:
            db = ScopedSession()
            close_db = True

        try:
            # Note: Signals are now global (no account_id)
            active_signals = db.query(TradingSignal).filter(
                TradingSignal.symbol == symbol,
                TradingSignal.status == 'active'
            ).order_by(TradingSignal.timeframe).all()

            summary = {
                'symbol': symbol,
                'timeframes': {},
                'conflicts': [],
                'aligned_groups': []
            }

            buy_signals = []
            sell_signals = []

            for signal in active_signals:
                tf_data = {
                    'timeframe': signal.timeframe,
                    'signal_type': signal.signal_type,
                    'confidence': float(signal.confidence or 0),
                    'created_at': signal.created_at.isoformat()
                }

                summary['timeframes'][signal.timeframe] = tf_data

                if signal.signal_type == 'BUY':
                    buy_signals.append(signal.timeframe)
                else:
                    sell_signals.append(signal.timeframe)

            # Detect conflicts
            if buy_signals and sell_signals:
                summary['conflicts'].append({
                    'buy_timeframes': buy_signals,
                    'sell_timeframes': sell_signals,
                    'severity': 'HIGH' if len(buy_signals) > 1 and len(sell_signals) > 1 else 'MEDIUM'
                })

            # Detect alignment
            if len(buy_signals) >= 2:
                summary['aligned_groups'].append({
                    'direction': 'BUY',
                    'timeframes': buy_signals,
                    'count': len(buy_signals)
                })
            if len(sell_signals) >= 2:
                summary['aligned_groups'].append({
                    'direction': 'SELL',
                    'timeframes': sell_signals,
                    'count': len(sell_signals)
                })

            return summary

        except Exception as e:
            logger.error(f"Error getting multi-timeframe summary: {e}", exc_info=True)
            return {'symbol': symbol, 'timeframes': {}, 'conflicts': [], 'aligned_groups': []}
        finally:
            if close_db:
                db.close()


# Quick access function
def check_multi_timeframe_conflict(
    signal_type: str,
    timeframe: str,
    symbol: str,
    account_id: int,
    db: Optional[Session] = None
) -> Dict:
    """
    Quick access function for multi-timeframe conflict check.

    Returns:
        Dict with has_conflict, confidence_adjustment, reason
    """
    return MultiTimeframeAnalyzer.check_conflict(
        signal_type, timeframe, symbol, account_id, db
    )
