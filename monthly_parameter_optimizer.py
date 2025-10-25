#!/usr/bin/env python3
"""
Monthly Parameter Optimizer for Heiken Ashi Trend Indicator
Runs on last Friday of each month at 23:00 UTC
Generates parameter optimization recommendations with safeguards
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
from decimal import Decimal
import json

from sqlalchemy import create_engine, and_, func, desc
from sqlalchemy.orm import sessionmaker
from parameter_versioning_models import (
    Base, ParameterOptimizationRun, IndicatorParameterVersion
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import Trade, TradingSignal

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MonthlyParameterOptimizer:
    """Optimizes Heiken Ashi indicator parameters monthly"""

    # Safeguard thresholds
    MIN_DATA_DAYS = 90
    MIN_TRADES = 200
    MAX_PARAM_CHANGE = 0.20  # ±20% max
    MIN_IMPROVEMENT_SCORE = 5.0  # Minimum score to recommend change

    def __init__(self, db_session=None):
        self.session = db_session or SessionLocal()
        self.indicator_name = 'HEIKEN_ASHI_TREND'

    def get_historical_trades(
        self,
        symbol: str,
        timeframe: str,
        days_back: int = 90
    ) -> List[Trade]:
        """Get historical trades for analysis"""

        start_date = datetime.utcnow() - timedelta(days=days_back)

        trades = self.session.query(Trade).join(
            TradingSignal,
            Trade.signal_id == TradingSignal.id
        ).filter(
            and_(
                Trade.symbol == symbol,
                Trade.timeframe == timeframe,
                Trade.created_at >= start_date,
                Trade.status.in_(['closed', 'completed']),
                TradingSignal.indicators_used.has_key('HEIKEN_ASHI_TREND')
            )
        ).all()

        return trades

    def calculate_performance_metrics(
        self,
        trades: List[Trade]
    ) -> Dict:
        """Calculate comprehensive performance metrics"""

        if not trades:
            return None

        total_trades = len(trades)
        winning_trades = [t for t in trades if t.profit and float(t.profit) > 0]
        losing_trades = [t for t in trades if t.profit and float(t.profit) < 0]

        win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0
        total_pnl = sum(float(t.profit) for t in trades if t.profit)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0

        avg_win = sum(float(t.profit) for t in winning_trades if t.profit) / len(winning_trades) if winning_trades else 0
        avg_loss = abs(sum(float(t.profit) for t in losing_trades if t.profit)) / len(losing_trades) if losing_trades else 0
        rr_ratio = avg_win / avg_loss if avg_loss > 0 else 0

        # Calculate profit factor
        total_wins = sum(float(t.profit) for t in winning_trades if t.profit)
        total_losses = abs(sum(float(t.profit) for t in losing_trades if t.profit))
        profit_factor = total_wins / total_losses if total_losses > 0 else 0

        # Max drawdown (simplified)
        cumulative_pnl = 0
        peak = 0
        max_dd = 0
        for trade in trades:
            if trade.profit:
                cumulative_pnl += float(trade.profit)
                if cumulative_pnl > peak:
                    peak = cumulative_pnl
                drawdown = peak - cumulative_pnl
                if drawdown > max_dd:
                    max_dd = drawdown

        return {
            'total_trades': total_trades,
            'win_rate': round(win_rate, 2),
            'total_pnl': round(total_pnl, 2),
            'avg_pnl': round(avg_pnl, 4),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'rr_ratio': round(rr_ratio, 2),
            'profit_factor': round(profit_factor, 2),
            'max_drawdown': round(max_dd, 2)
        }

    def assess_data_quality(
        self,
        trades: List[Trade],
        days_back: int
    ) -> Tuple[int, str]:
        """Assess data quality and return score (0-100)"""

        if not trades:
            return 0, "No trades found"

        score = 100
        issues = []

        # Check 1: Minimum trades
        if len(trades) < self.MIN_TRADES:
            score -= 40
            issues.append(f"Only {len(trades)} trades (min: {self.MIN_TRADES})")

        # Check 2: Minimum days
        if days_back < self.MIN_DATA_DAYS:
            score -= 30
            issues.append(f"Only {days_back} days (min: {self.MIN_DATA_DAYS})")

        # Check 3: Trade distribution over time
        trades_per_day = len(trades) / days_back
        if trades_per_day < 1.0:
            score -= 20
            issues.append(f"Low trade frequency: {trades_per_day:.1f}/day")

        # Check 4: Direction balance (should have both BUY and SELL)
        buy_count = len([t for t in trades if t.direction == 'BUY'])
        sell_count = len([t for t in trades if t.direction == 'SELL'])
        if buy_count == 0 or sell_count == 0:
            score -= 10
            issues.append("Only one direction traded")

        score = max(0, score)
        status = "excellent" if score >= 80 else "good" if score >= 60 else "fair" if score >= 40 else "poor"

        message = f"{status} ({score}/100)"
        if issues:
            message += f" - {'; '.join(issues)}"

        return score, message

    def generate_parameter_recommendations(
        self,
        symbol: str,
        timeframe: str,
        current_params: Dict,
        current_performance: Dict
    ) -> Optional[Dict]:
        """Generate parameter optimization recommendations"""

        # For Heiken Ashi, parameters to optimize:
        # - min_confidence (60-80)
        # - sl_multiplier (1.0-3.0)
        # - tp_multiplier (2.0-5.0)

        recommended = current_params.copy()
        changes_made = []

        # Rule 1: If win rate > 45% but low P/L, increase TP multiplier
        if current_performance['win_rate'] > 45 and current_performance['rr_ratio'] < 1.5:
            old_tp = current_params.get('tp_multiplier', 3.0)
            new_tp = min(old_tp * 1.2, 5.0)  # Max 20% increase, cap at 5.0
            if abs(new_tp - old_tp) / old_tp <= self.MAX_PARAM_CHANGE:
                recommended['tp_multiplier'] = round(new_tp, 1)
                changes_made.append(f"TP multiplier: {old_tp} → {new_tp:.1f} (improve R/R)")

        # Rule 2: If win rate < 40%, lower min_confidence to get more trades
        if current_performance['win_rate'] < 40 and current_performance['total_trades'] < 50:
            old_conf = current_params.get('min_confidence', 60)
            new_conf = max(old_conf - 5, 50)  # Lower by 5, min 50
            if abs(new_conf - old_conf) / old_conf <= self.MAX_PARAM_CHANGE:
                recommended['min_confidence'] = new_conf
                changes_made.append(f"Min confidence: {old_conf} → {new_conf} (increase trade count)")

        # Rule 3: If win rate > 50%, increase min_confidence for quality
        if current_performance['win_rate'] > 50 and current_performance['total_trades'] > 100:
            old_conf = current_params.get('min_confidence', 60)
            new_conf = min(old_conf + 5, 80)  # Increase by 5, max 80
            if abs(new_conf - old_conf) / old_conf <= self.MAX_PARAM_CHANGE:
                recommended['min_confidence'] = new_conf
                changes_made.append(f"Min confidence: {old_conf} → {new_conf} (focus on quality)")

        # Rule 4: If max drawdown > 20 EUR, tighten SL
        if current_performance['max_drawdown'] > 20:
            old_sl = current_params.get('sl_multiplier', 1.5)
            new_sl = max(old_sl * 0.9, 1.0)  # Reduce by 10%, min 1.0
            if abs(new_sl - old_sl) / old_sl <= self.MAX_PARAM_CHANGE:
                recommended['sl_multiplier'] = round(new_sl, 1)
                changes_made.append(f"SL multiplier: {old_sl} → {new_sl:.1f} (reduce drawdown)")

        # Rule 5: If R/R ratio > 2.0, can afford to widen SL slightly for more entries
        if current_performance['rr_ratio'] > 2.0 and current_performance['total_trades'] < 50:
            old_sl = current_params.get('sl_multiplier', 1.5)
            new_sl = min(old_sl * 1.1, 3.0)  # Increase by 10%, max 3.0
            if abs(new_sl - old_sl) / old_sl <= self.MAX_PARAM_CHANGE:
                recommended['sl_multiplier'] = round(new_sl, 1)
                changes_made.append(f"SL multiplier: {old_sl} → {new_sl:.1f} (allow more entries)")

        if not changes_made:
            return None

        # Simulate expected improvement (simplified heuristic)
        expected_metrics = current_performance.copy()

        # If we increased TP, expect higher R/R
        if recommended.get('tp_multiplier', 0) > current_params.get('tp_multiplier', 0):
            expected_metrics['rr_ratio'] = min(expected_metrics['rr_ratio'] * 1.15, 3.0)

        # If we changed confidence, expect different trade count
        conf_change = recommended.get('min_confidence', 60) - current_params.get('min_confidence', 60)
        if conf_change > 0:
            expected_metrics['win_rate'] = min(expected_metrics['win_rate'] * 1.05, 100)
            expected_metrics['total_trades'] = int(expected_metrics['total_trades'] * 0.8)
        elif conf_change < 0:
            expected_metrics['win_rate'] = expected_metrics['win_rate'] * 0.95
            expected_metrics['total_trades'] = int(expected_metrics['total_trades'] * 1.2)

        return {
            'recommended_parameters': recommended,
            'expected_performance': expected_metrics,
            'changes': changes_made
        }

    def calculate_improvement_score(
        self,
        current_perf: Dict,
        expected_perf: Dict
    ) -> float:
        """Calculate improvement score (0-100)"""

        score = 0

        # Win rate improvement (weight: 40%)
        wr_improvement = expected_perf['win_rate'] - current_perf['win_rate']
        score += wr_improvement * 0.4

        # P/L improvement (weight: 30%)
        pnl_improvement = expected_perf['total_pnl'] - current_perf['total_pnl']
        pnl_pct = (pnl_improvement / abs(current_perf['total_pnl'])) * 100 if current_perf['total_pnl'] != 0 else 0
        score += pnl_pct * 0.3

        # R/R improvement (weight: 20%)
        rr_improvement = expected_perf['rr_ratio'] - current_perf['rr_ratio']
        rr_pct = (rr_improvement / current_perf['rr_ratio']) * 100 if current_perf['rr_ratio'] > 0 else 0
        score += rr_pct * 0.2

        # Drawdown reduction (weight: 10%)
        dd_improvement = current_perf['max_drawdown'] - expected_perf['max_drawdown']
        dd_pct = (dd_improvement / current_perf['max_drawdown']) * 100 if current_perf['max_drawdown'] > 0 else 0
        score += dd_pct * 0.1

        return round(score, 2)

    def check_safeguards(
        self,
        data_quality_score: int,
        trades_count: int,
        days_back: int,
        current_params: Dict,
        recommended_params: Dict
    ) -> Tuple[bool, List[str]]:
        """Check all safeguards before recommending changes"""

        passed = True
        failures = []

        # Safeguard 1: Minimum data quality
        if data_quality_score < 60:
            passed = False
            failures.append(f"Data quality too low: {data_quality_score}/100 (min: 60)")

        # Safeguard 2: Minimum trades
        if trades_count < self.MIN_TRADES:
            passed = False
            failures.append(f"Insufficient trades: {trades_count} (min: {self.MIN_TRADES})")

        # Safeguard 3: Minimum days
        if days_back < self.MIN_DATA_DAYS:
            passed = False
            failures.append(f"Insufficient data period: {days_back} days (min: {self.MIN_DATA_DAYS})")

        # Safeguard 4: Maximum parameter change
        for key in recommended_params:
            if key in current_params:
                old_val = current_params[key]
                new_val = recommended_params[key]
                if old_val != 0:
                    change_pct = abs(new_val - old_val) / abs(old_val)
                    if change_pct > self.MAX_PARAM_CHANGE:
                        passed = False
                        failures.append(
                            f"Parameter {key} change too large: {change_pct*100:.1f}% (max: {self.MAX_PARAM_CHANGE*100}%)"
                        )

        return passed, failures

    def optimize_symbol(
        self,
        symbol: str,
        timeframe: str,
        days_back: int = 90
    ) -> Optional[int]:
        """Run optimization for a specific symbol/timeframe"""

        logger.info(f"Optimizing {symbol} {timeframe}...")

        # Get current active version
        current_version = self.session.query(IndicatorParameterVersion).filter(
            and_(
                IndicatorParameterVersion.indicator_name == self.indicator_name,
                IndicatorParameterVersion.symbol == symbol,
                IndicatorParameterVersion.timeframe == timeframe,
                IndicatorParameterVersion.status == 'active'
            )
        ).first()

        if not current_version:
            logger.warning(f"No active version for {symbol} {timeframe}")
            return None

        current_params = current_version.parameters

        # Get historical trades
        trades = self.get_historical_trades(symbol, timeframe, days_back)

        if not trades:
            logger.warning(f"No trades found for {symbol} {timeframe}")
            return None

        # Assess data quality
        data_quality_score, quality_message = self.assess_data_quality(trades, days_back)
        logger.info(f"Data quality: {quality_message}")

        # Calculate current performance
        current_perf = self.calculate_performance_metrics(trades)
        logger.info(f"Current performance: WR={current_perf['win_rate']}%, P/L={current_perf['total_pnl']}, Trades={current_perf['total_trades']}")

        # Generate recommendations
        optimization = self.generate_parameter_recommendations(
            symbol, timeframe, current_params, current_perf
        )

        if not optimization:
            logger.info(f"No parameter changes recommended for {symbol} {timeframe}")

            # Still create a record (recommendation: keep)
            run = ParameterOptimizationRun(
                indicator_name=self.indicator_name,
                symbol=symbol,
                timeframe=timeframe,
                data_days=days_back,
                data_trades=len(trades),
                data_quality_score=Decimal(str(data_quality_score)),
                current_version_id=current_version.id,
                current_parameters=current_params,
                current_performance=current_perf,
                recommended_parameters=current_params,
                recommended_performance=current_perf,
                improvement_win_rate=Decimal('0'),
                improvement_pnl=Decimal('0'),
                improvement_score=Decimal('0'),
                safeguards_passed=True,
                safeguard_details={'message': 'No changes needed'},
                recommendation='keep',
                confidence='high',
                reason='Current parameters performing within acceptable range',
                status='pending_review'
            )

            self.session.add(run)
            self.session.commit()
            return run.id

        recommended_params = optimization['recommended_parameters']
        expected_perf = optimization['expected_performance']

        # Calculate improvements
        wr_improvement = expected_perf['win_rate'] - current_perf['win_rate']
        pnl_improvement = expected_perf['total_pnl'] - current_perf['total_pnl']
        improvement_score = self.calculate_improvement_score(current_perf, expected_perf)

        logger.info(f"Recommended changes: {optimization['changes']}")
        logger.info(f"Expected improvements: WR +{wr_improvement:.2f}%, P/L +{pnl_improvement:.2f}, Score: {improvement_score:.2f}")

        # Check safeguards
        safeguards_passed, failures = self.check_safeguards(
            data_quality_score,
            len(trades),
            days_back,
            current_params,
            recommended_params
        )

        if not safeguards_passed:
            logger.warning(f"Safeguards failed: {failures}")

        # Determine recommendation and confidence
        if not safeguards_passed:
            recommendation = 'keep'
            confidence = 'low'
            reason = f"Safeguards failed: {'; '.join(failures)}"
        elif improvement_score < self.MIN_IMPROVEMENT_SCORE:
            recommendation = 'keep'
            confidence = 'medium'
            reason = f"Improvement score too low ({improvement_score:.2f} < {self.MIN_IMPROVEMENT_SCORE})"
        elif current_perf['win_rate'] < 35:
            recommendation = 'disable'
            confidence = 'high'
            reason = f"Win rate critically low ({current_perf['win_rate']}%)"
        elif improvement_score >= 15:
            recommendation = 'adjust'
            confidence = 'high'
            reason = f"Significant improvement expected ({improvement_score:.2f} points)"
        elif improvement_score >= 10:
            recommendation = 'adjust'
            confidence = 'medium'
            reason = f"Moderate improvement expected ({improvement_score:.2f} points)"
        else:
            recommendation = 'adjust'
            confidence = 'low'
            reason = f"Minor improvement expected ({improvement_score:.2f} points)"

        # Create optimization run record
        run = ParameterOptimizationRun(
            indicator_name=self.indicator_name,
            symbol=symbol,
            timeframe=timeframe,
            data_days=days_back,
            data_trades=len(trades),
            data_quality_score=Decimal(str(data_quality_score)),
            current_version_id=current_version.id,
            current_parameters=current_params,
            current_performance=current_perf,
            recommended_parameters=recommended_params,
            recommended_performance=expected_perf,
            improvement_win_rate=Decimal(str(round(wr_improvement, 2))),
            improvement_pnl=Decimal(str(round(pnl_improvement, 2))),
            improvement_score=Decimal(str(improvement_score)),
            safeguards_passed=safeguards_passed,
            safeguard_details={
                'data_quality_score': data_quality_score,
                'trades_count': len(trades),
                'days_back': days_back,
                'failures': failures if not safeguards_passed else []
            },
            recommendation=recommendation,
            confidence=confidence,
            reason=reason,
            status='pending_review'
        )

        self.session.add(run)
        self.session.commit()

        logger.info(f"✅ Optimization run created (ID: {run.id}) - Recommendation: {recommendation} ({confidence})")

        return run.id

    def run_monthly_optimization(self) -> Dict[str, int]:
        """Run optimization for all active symbols"""

        logger.info("Starting monthly parameter optimization...")

        # Get all active symbol/timeframe configs
        active_versions = self.session.query(IndicatorParameterVersion).filter(
            and_(
                IndicatorParameterVersion.indicator_name == self.indicator_name,
                IndicatorParameterVersion.status == 'active'
            )
        ).all()

        if not active_versions:
            logger.warning("No active Heiken Ashi parameter versions found")
            return {}

        results = {}

        for version in active_versions:
            symbol = version.symbol
            timeframe = version.timeframe

            try:
                run_id = self.optimize_symbol(symbol, timeframe, days_back=90)
                results[f"{symbol}_{timeframe}"] = run_id
            except Exception as e:
                logger.error(f"Error optimizing {symbol} {timeframe}: {e}", exc_info=True)
                results[f"{symbol}_{timeframe}"] = None

        logger.info(f"✅ Monthly optimization complete - {len(results)} symbols processed")

        return results


def main():
    """Main entry point for monthly optimization"""

    optimizer = MonthlyParameterOptimizer()

    try:
        results = optimizer.run_monthly_optimization()

        total = len(results)
        successful = len([r for r in results.values() if r is not None])

        print(f"✅ Monthly parameter optimization complete")
        print(f"📊 Processed: {successful}/{total} symbols")
        print(f"💾 View results in database: parameter_optimization_runs")

        return 0 if successful > 0 else 1

    except Exception as e:
        logger.error(f"Error running monthly optimization: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
