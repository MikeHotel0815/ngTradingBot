#!/usr/bin/env python3
"""
Weekly Performance Analyzer for Heiken Ashi Trend Indicator
Runs every Friday at 22:00 UTC
Analyzes performance over 7/30/90 day periods and generates reports
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
from decimal import Decimal

from sqlalchemy import create_engine, and_, func, desc
from sqlalchemy.orm import sessionmaker
from parameter_versioning_models import (
    Base, WeeklyPerformanceReport, IndicatorParameterVersion
)

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import Trade, TradingSignal
from telegram_notifier import get_telegram_notifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WeeklyPerformanceAnalyzer:
    """Analyzes Heiken Ashi indicator performance weekly"""

    def __init__(self, db_session=None):
        self.session = db_session or SessionLocal()
        self.indicator_name = 'HEIKEN_ASHI_TREND'
        self.lookback_periods = [7, 30, 90]
        self.telegram = get_telegram_notifier()
        self.ai_reports_dir = '/app/ai_analysis_reports'

        # Create AI reports directory if it doesn't exist
        os.makedirs(self.ai_reports_dir, exist_ok=True)

    def analyze_symbol_performance(
        self,
        symbol: str,
        timeframe: str,
        days_back: int
    ) -> Optional[Dict]:
        """Analyze performance for a specific symbol/timeframe over N days"""

        start_date = datetime.utcnow() - timedelta(days=days_back)

        # Query trades that used HEIKEN_ASHI_TREND signals
        # Join with TradingSignal to check indicators_used
        trades = self.session.query(Trade).join(
            TradingSignal,
            Trade.signal_id == TradingSignal.id
        ).filter(
            and_(
                Trade.symbol == symbol,
                Trade.timeframe == timeframe,
                Trade.created_at >= start_date,
                Trade.status.in_(['closed', 'completed']),
                # Check if indicators_used contains HEIKEN_ASHI_TREND
                TradingSignal.indicators_used.has_key('HEIKEN_ASHI_TREND')
            )
        ).all()

        if not trades:
            logger.info(f"No {symbol} {timeframe} trades found in last {days_back} days")
            return None

        # Calculate metrics
        total_trades = len(trades)
        winning_trades = [t for t in trades if t.profit and float(t.profit) > 0]
        losing_trades = [t for t in trades if t.profit and float(t.profit) < 0]

        win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0

        total_pnl = sum(float(t.profit) for t in trades if t.profit)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0

        avg_win = sum(float(t.profit) for t in winning_trades if t.profit) / len(winning_trades) if winning_trades else 0
        avg_loss = abs(sum(float(t.profit) for t in losing_trades if t.profit)) / len(losing_trades) if losing_trades else 0

        rr_ratio = avg_win / avg_loss if avg_loss > 0 else 0

        # Calculate by direction
        buy_trades = [t for t in trades if t.direction == 'BUY']
        sell_trades = [t for t in trades if t.direction == 'SELL']

        buy_win_rate = (len([t for t in buy_trades if t.profit and float(t.profit) > 0]) / len(buy_trades) * 100) if buy_trades else 0
        sell_win_rate = (len([t for t in sell_trades if t.profit and float(t.profit) > 0]) / len(sell_trades) * 100) if sell_trades else 0

        buy_pnl = sum(float(t.profit) for t in buy_trades if t.profit)
        sell_pnl = sum(float(t.profit) for t in sell_trades if t.profit)

        return {
            'symbol': symbol,
            'timeframe': timeframe,
            'period_days': days_back,
            'total_trades': total_trades,
            'win_rate': round(win_rate, 2),
            'total_pnl': round(total_pnl, 2),
            'avg_pnl': round(avg_pnl, 4),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'rr_ratio': round(rr_ratio, 2),
            'direction_stats': {
                'buy': {
                    'count': len(buy_trades),
                    'win_rate': round(buy_win_rate, 2),
                    'pnl': round(buy_pnl, 2)
                },
                'sell': {
                    'count': len(sell_trades),
                    'win_rate': round(sell_win_rate, 2),
                    'pnl': round(sell_pnl, 2)
                }
            }
        }

    def get_baseline_performance(
        self,
        symbol: str,
        timeframe: str
    ) -> Optional[Dict]:
        """Get backtest baseline from parameter version"""

        version = self.session.query(IndicatorParameterVersion).filter(
            and_(
                IndicatorParameterVersion.indicator_name == self.indicator_name,
                IndicatorParameterVersion.symbol == symbol,
                IndicatorParameterVersion.timeframe == timeframe,
                IndicatorParameterVersion.status == 'active'
            )
        ).first()

        if not version:
            logger.warning(f"No active version found for {symbol} {timeframe}")
            return None

        return {
            'win_rate': float(version.backtest_win_rate) if version.backtest_win_rate else None,
            'total_pnl': float(version.backtest_total_pnl) if version.backtest_total_pnl else None,
            'avg_pnl': float(version.backtest_avg_pnl) if version.backtest_avg_pnl else None,
            'trades': version.backtest_trades,
            'period_days': version.backtest_period_days
        }

    def compare_to_baseline(
        self,
        live_metrics: Dict,
        baseline: Optional[Dict]
    ) -> Dict:
        """Compare live performance to backtest baseline"""

        if not baseline or not baseline.get('win_rate'):
            return {
                'status': 'no_baseline',
                'message': 'No baseline available for comparison'
            }

        # Compare win rate
        wr_diff = live_metrics['win_rate'] - baseline['win_rate']
        wr_pct_change = (wr_diff / baseline['win_rate'] * 100) if baseline['win_rate'] > 0 else 0

        # Compare total P/L (normalize by period if needed)
        pnl_diff = live_metrics['total_pnl'] - (baseline['total_pnl'] or 0)

        # Determine status
        if live_metrics['win_rate'] < 35:
            status = 'critical'
        elif wr_diff < -10:  # More than 10% drop in WR
            status = 'warning'
        elif wr_diff < -5:
            status = 'concern'
        elif wr_diff > 5:
            status = 'exceeding'
        else:
            status = 'on_track'

        return {
            'status': status,
            'win_rate_diff': round(wr_diff, 2),
            'win_rate_pct_change': round(wr_pct_change, 2),
            'pnl_diff': round(pnl_diff, 2),
            'baseline_wr': baseline['win_rate'],
            'live_wr': live_metrics['win_rate'],
            'baseline_pnl': baseline['total_pnl'],
            'live_pnl': live_metrics['total_pnl']
        }

    def detect_warnings(
        self,
        symbol_metrics: List[Dict],
        comparisons: Dict
    ) -> List[Dict]:
        """Detect performance warnings"""

        warnings = []

        for metrics in symbol_metrics:
            symbol = metrics['symbol']
            timeframe = metrics['timeframe']
            key = f"{symbol}_{timeframe}"

            # Warning 1: Win rate below 35%
            if metrics['win_rate'] < 35:
                warnings.append({
                    'severity': 'critical',
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'type': 'low_win_rate',
                    'message': f"Win rate critically low: {metrics['win_rate']}% (threshold: 35%)",
                    'value': metrics['win_rate']
                })

            # Warning 2: Significant drop from baseline
            comp = comparisons.get(key, {})
            if comp.get('status') == 'warning' or comp.get('status') == 'critical':
                warnings.append({
                    'severity': 'warning',
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'type': 'baseline_degradation',
                    'message': f"Performance dropped {comp.get('win_rate_diff', 0)}% from baseline",
                    'value': comp.get('win_rate_diff', 0)
                })

            # Warning 3: Very low trade count (insufficient data)
            if metrics['total_trades'] < 10:
                warnings.append({
                    'severity': 'info',
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'type': 'low_sample_size',
                    'message': f"Only {metrics['total_trades']} trades (min recommended: 10)",
                    'value': metrics['total_trades']
                })

            # Warning 4: Negative P/L
            if metrics['total_pnl'] < 0:
                warnings.append({
                    'severity': 'warning',
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'type': 'negative_pnl',
                    'message': f"Negative P/L: {metrics['total_pnl']} EUR",
                    'value': metrics['total_pnl']
                })

            # Warning 5: Poor R/R ratio
            if metrics['rr_ratio'] < 1.0 and metrics['total_trades'] >= 10:
                warnings.append({
                    'severity': 'warning',
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'type': 'poor_rr_ratio',
                    'message': f"R/R ratio below 1.0: {metrics['rr_ratio']}",
                    'value': metrics['rr_ratio']
                })

        return warnings

    def generate_summary(
        self,
        symbol_metrics: List[Dict],
        warnings: List[Dict]
    ) -> str:
        """Generate human-readable summary"""

        total_trades = sum(m['total_trades'] for m in symbol_metrics)
        total_pnl = sum(m['total_pnl'] for m in symbol_metrics)

        # Calculate weighted average win rate
        if total_trades > 0:
            weighted_wr = sum(m['win_rate'] * m['total_trades'] for m in symbol_metrics) / total_trades
        else:
            weighted_wr = 0

        critical_warnings = [w for w in warnings if w['severity'] == 'critical']
        warning_count = [w for w in warnings if w['severity'] == 'warning']

        summary = f"""HEIKEN ASHI TREND - Weekly Performance Report
Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

OVERALL PERFORMANCE (30 Days):
- Total Trades: {total_trades}
- Weighted Win Rate: {weighted_wr:.2f}%
- Total P/L: {total_pnl:+.2f} EUR

SYMBOLS ANALYZED: {len(symbol_metrics)}
"""

        if critical_warnings:
            summary += f"\n⚠️  CRITICAL ISSUES: {len(critical_warnings)}"
            for w in critical_warnings[:3]:  # Top 3
                summary += f"\n   - {w['symbol']} {w['timeframe']}: {w['message']}"

        if warning_count:
            summary += f"\n\n⚡ WARNINGS: {len(warning_count)}"
            for w in warning_count[:3]:  # Top 3
                summary += f"\n   - {w['symbol']} {w['timeframe']}: {w['message']}"

        if not critical_warnings and not warning_count:
            summary += "\n\n✅ No critical issues detected"

        return summary

    def generate_recommendations(
        self,
        warnings: List[Dict],
        comparisons: Dict
    ) -> str:
        """Generate actionable recommendations"""

        recommendations = []

        # Recommendation 1: Disable underperforming configs
        critical_symbols = [w for w in warnings if w['severity'] == 'critical' and w['type'] == 'low_win_rate']
        if critical_symbols:
            recommendations.append(
                f"DISABLE: Consider disabling {len(critical_symbols)} symbol/timeframe configs with WR < 35%:"
            )
            for w in critical_symbols[:3]:
                recommendations.append(f"  - {w['symbol']} {w['timeframe']} (WR: {w['value']:.1f}%)")

        # Recommendation 2: Parameter optimization needed
        degraded = [k for k, v in comparisons.items() if v.get('status') in ['warning', 'critical']]
        if degraded:
            recommendations.append(
                f"\nOPTIMIZE: {len(degraded)} configs showing performance degradation - schedule optimization run"
            )

        # Recommendation 3: Insufficient data
        low_sample = [w for w in warnings if w['type'] == 'low_sample_size']
        if low_sample:
            recommendations.append(
                f"\nMONITOR: {len(low_sample)} configs have < 10 trades - wait for more data before making changes"
            )

        if not recommendations:
            recommendations.append("✅ All symbols performing within expected parameters - no immediate action needed")

        return "\n".join(recommendations)

    def send_telegram_notification(
        self,
        summary: str,
        warnings: List[Dict],
        symbol_metrics: List[Dict]
    ) -> bool:
        """Send weekly report via Telegram"""

        if not self.telegram.enabled:
            logger.warning("Telegram not enabled - skipping notification")
            return False

        # Format for Telegram (compact, readable)
        now = datetime.utcnow()
        week_num = now.isocalendar()[1]

        total_trades = sum(m['total_trades'] for m in symbol_metrics)
        total_pnl = sum(m['total_pnl'] for m in symbol_metrics)
        weighted_wr = sum(m['win_rate'] * m['total_trades'] for m in symbol_metrics) / total_trades if total_trades > 0 else 0

        # Emoji based on performance
        if total_pnl > 0:
            pnl_emoji = '✅'
        elif total_pnl < 0:
            pnl_emoji = '❌'
        else:
            pnl_emoji = '➖'

        # Build message
        message = f"""📊 <b>HEIKEN ASHI Weekly Report</b>
Week {week_num}/2025 | {now.strftime('%d.%m.%Y')}

{pnl_emoji} <b>€{total_pnl:+.2f}</b> | {total_trades} Trades
Win Rate: {weighted_wr:.1f}%

<b>SYMBOLS:</b>"""

        # Add symbol details (top 3 by P/L)
        sorted_metrics = sorted(symbol_metrics, key=lambda m: m['total_pnl'], reverse=True)
        for m in sorted_metrics[:3]:
            emoji = '✅' if m['total_pnl'] > 0 else '❌'
            message += f"\n{emoji} {m['symbol']} {m['timeframe']}: €{m['total_pnl']:+.2f} ({m['win_rate']:.0f}%, {m['total_trades']}T)"

        if len(sorted_metrics) > 3:
            message += f"\n... +{len(sorted_metrics) - 3} more"

        # Add critical warnings
        critical_warnings = [w for w in warnings if w['severity'] == 'critical']
        if critical_warnings:
            message += f"\n\n🚨 <b>CRITICAL:</b> {len(critical_warnings)} issues"
            for w in critical_warnings[:2]:
                message += f"\n• {w['symbol']} {w['timeframe']}: {w['message']}"

        # Add info footer
        message += f"\n\n<i>Full report: ai_analysis_reports/weekly_report_{now.strftime('%Y%m%d')}.json</i>"

        try:
            return self.telegram.send_message(message, silent=False)
        except Exception as e:
            logger.error(f"Error sending Telegram notification: {e}")
            return False

    def save_ai_analysis_report(
        self,
        report_id: int,
        symbol_metrics: List[Dict],
        comparisons: Dict,
        warnings: List[Dict],
        summary: str,
        recommendations: str
    ) -> str:
        """Save detailed analysis report for AI access"""

        import json

        now = datetime.utcnow()
        filename = f"weekly_report_{now.strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(self.ai_reports_dir, filename)

        # Build comprehensive report for AI
        ai_report = {
            'report_metadata': {
                'report_id': report_id,
                'generated_at': now.isoformat(),
                'report_type': 'weekly_performance',
                'indicator': self.indicator_name,
                'week_number': now.isocalendar()[1],
                'year': now.year
            },
            'overall_performance': {
                'total_trades': sum(m['total_trades'] for m in symbol_metrics),
                'total_pnl': sum(m['total_pnl'] for m in symbol_metrics),
                'weighted_win_rate': sum(m['win_rate'] * m['total_trades'] for m in symbol_metrics) / sum(m['total_trades'] for m in symbol_metrics) if sum(m['total_trades'] for m in symbol_metrics) > 0 else 0,
                'avg_rr_ratio': sum(m['rr_ratio'] for m in symbol_metrics) / len(symbol_metrics) if symbol_metrics else 0
            },
            'symbol_performance': symbol_metrics,
            'baseline_comparison': comparisons,
            'warnings': warnings,
            'analysis': {
                'summary': summary,
                'recommendations': recommendations,
                'critical_count': len([w for w in warnings if w['severity'] == 'critical']),
                'warning_count': len([w for w in warnings if w['severity'] == 'warning']),
                'symbols_tracked': len(symbol_metrics)
            },
            'ai_insights': {
                'best_performer': max(symbol_metrics, key=lambda m: m['total_pnl']) if symbol_metrics else None,
                'worst_performer': min(symbol_metrics, key=lambda m: m['total_pnl']) if symbol_metrics else None,
                'highest_wr': max(symbol_metrics, key=lambda m: m['win_rate']) if symbol_metrics else None,
                'lowest_wr': min(symbol_metrics, key=lambda m: m['win_rate']) if symbol_metrics else None,
                'degradation_detected': [k for k, v in comparisons.items() if v.get('status') in ['warning', 'critical']],
                'symbols_needing_attention': [w['symbol'] + '_' + w['timeframe'] for w in warnings if w['severity'] == 'critical']
            }
        }

        # Save to file
        try:
            with open(filepath, 'w') as f:
                json.dump(ai_report, f, indent=2, default=str)

            logger.info(f"✅ AI analysis report saved: {filepath}")

            # Also save a "latest.json" for easy AI access
            latest_path = os.path.join(self.ai_reports_dir, 'latest_weekly_report.json')
            with open(latest_path, 'w') as f:
                json.dump(ai_report, f, indent=2, default=str)

            return filepath

        except Exception as e:
            logger.error(f"Error saving AI analysis report: {e}")
            return None

    def generate_weekly_report(self) -> Optional[int]:
        """Generate complete weekly performance report"""

        logger.info("Starting weekly performance analysis...")

        # Get all active symbol/timeframe configs
        active_versions = self.session.query(IndicatorParameterVersion).filter(
            and_(
                IndicatorParameterVersion.indicator_name == self.indicator_name,
                IndicatorParameterVersion.status == 'active'
            )
        ).all()

        if not active_versions:
            logger.warning("No active Heiken Ashi parameter versions found")
            return None

        # Analyze each symbol/timeframe over all lookback periods
        all_metrics = []
        comparisons = {}

        for version in active_versions:
            symbol = version.symbol
            timeframe = version.timeframe

            logger.info(f"Analyzing {symbol} {timeframe}...")

            # Get 30-day metrics (primary period)
            metrics_30d = self.analyze_symbol_performance(symbol, timeframe, 30)

            if metrics_30d:
                all_metrics.append(metrics_30d)

                # Compare to baseline
                baseline = self.get_baseline_performance(symbol, timeframe)
                comparison = self.compare_to_baseline(metrics_30d, baseline)
                comparisons[f"{symbol}_{timeframe}"] = comparison

        if not all_metrics:
            logger.warning("No metrics generated - no trades found")
            return None

        # Detect warnings
        warnings = self.detect_warnings(all_metrics, comparisons)

        # Generate summary and recommendations
        summary = self.generate_summary(all_metrics, warnings)
        recommendations = self.generate_recommendations(warnings, comparisons)

        # Calculate overall metrics
        total_trades = sum(m['total_trades'] for m in all_metrics)
        total_pnl = sum(m['total_pnl'] for m in all_metrics)
        weighted_wr = sum(m['win_rate'] * m['total_trades'] for m in all_metrics) / total_trades if total_trades > 0 else 0

        # Get current week number
        now = datetime.utcnow()
        week_number = now.isocalendar()[1]
        year = now.year

        # Create report record
        report = WeeklyPerformanceReport(
            report_date=now.date(),
            week_number=week_number,
            year=year,
            total_trades=total_trades,
            total_win_rate=Decimal(str(round(weighted_wr, 2))),
            total_pnl=Decimal(str(round(total_pnl, 2))),
            symbol_metrics=all_metrics,
            baseline_comparison=comparisons,
            warnings=warnings,
            lookback_periods=self.lookback_periods,
            report_type='weekly',
            summary=summary,
            recommendations=recommendations,
            full_report={
                'generated_at': now.isoformat(),
                'active_configs': len(active_versions),
                'metrics_count': len(all_metrics),
                'warning_count': len(warnings),
                'critical_count': len([w for w in warnings if w['severity'] == 'critical'])
            }
        )

        self.session.add(report)
        self.session.commit()

        logger.info(f"✅ Weekly report generated (ID: {report.id})")
        logger.info(f"\n{summary}")
        logger.info(f"\nRECOMMENDATIONS:\n{recommendations}")

        # Send Telegram notification
        telegram_sent = self.send_telegram_notification(summary, warnings, all_metrics)
        if telegram_sent:
            logger.info("✅ Telegram notification sent")
        else:
            logger.warning("⚠️  Telegram notification not sent")

        # Save AI-accessible report
        ai_report_path = self.save_ai_analysis_report(
            report.id,
            all_metrics,
            comparisons,
            warnings,
            summary,
            recommendations
        )
        if ai_report_path:
            logger.info(f"✅ AI analysis report saved: {ai_report_path}")

        return report.id


def main():
    """Main entry point for weekly performance analysis"""

    analyzer = WeeklyPerformanceAnalyzer()

    try:
        report_id = analyzer.generate_weekly_report()

        if report_id:
            print(f"✅ Weekly performance report generated (ID: {report_id})")
            print(f"📊 View in database: weekly_performance_reports")
            return 0
        else:
            print("⚠️  No report generated (no active configs or trades)")
            return 1

    except Exception as e:
        logger.error(f"Error generating weekly report: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
