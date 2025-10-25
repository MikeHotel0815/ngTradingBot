#!/usr/bin/env python3
"""
Top Performers Analyzer
Analyzes and ranks top 10 indicators and pattern recognitions
Based on last 14 days performance
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from decimal import Decimal
from collections import defaultdict

from sqlalchemy import and_, func, desc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import Trade, TradingSignal
from telegram_notifier import get_telegram_notifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TopPerformersAnalyzer:
    """Analyze and rank top performing indicators and patterns"""

    def __init__(self, db_session=None, days_back: int = 14):
        self.session = db_session or SessionLocal()
        self.days_back = days_back
        self.telegram = get_telegram_notifier()
        self.ai_reports_dir = '/app/ai_analysis_reports'

        # Create AI reports directory if it doesn't exist
        os.makedirs(self.ai_reports_dir, exist_ok=True)

    def get_indicator_performance(self) -> List[Dict]:
        """Analyze performance of all indicators over last N days"""

        start_date = datetime.utcnow() - timedelta(days=self.days_back)

        # Query all closed trades with signal info
        trades = self.session.query(Trade, TradingSignal).join(
            TradingSignal,
            Trade.signal_id == TradingSignal.id
        ).filter(
            and_(
                Trade.created_at >= start_date,
                Trade.status.in_(['closed', 'completed']),
                TradingSignal.indicators_used.isnot(None)
            )
        ).all()

        if not trades:
            logger.warning(f"No trades found in last {self.days_back} days")
            return []

        # Aggregate by indicator
        indicator_stats = defaultdict(lambda: {
            'trades': [],
            'total_pnl': 0,
            'wins': 0,
            'losses': 0,
            'total_trades': 0
        })

        for trade, signal in trades:
            if not signal.indicators_used:
                continue

            # Each trade can use multiple indicators
            for indicator_name in signal.indicators_used.keys():
                stats = indicator_stats[indicator_name]
                stats['trades'].append(trade)
                stats['total_trades'] += 1

                pnl = float(trade.profit) if trade.profit else 0
                stats['total_pnl'] += pnl

                if pnl > 0:
                    stats['wins'] += 1
                elif pnl < 0:
                    stats['losses'] += 1

        # Calculate metrics
        results = []
        for indicator_name, stats in indicator_stats.items():
            total_trades = stats['total_trades']
            if total_trades == 0:
                continue

            win_rate = (stats['wins'] / total_trades * 100) if total_trades > 0 else 0
            avg_pnl = stats['total_pnl'] / total_trades

            # Calculate profit factor
            winning_trades = [t for t in stats['trades'] if t.profit and float(t.profit) > 0]
            losing_trades = [t for t in stats['trades'] if t.profit and float(t.profit) < 0]

            total_wins = sum(float(t.profit) for t in winning_trades if t.profit)
            total_losses = abs(sum(float(t.profit) for t in losing_trades if t.profit))

            profit_factor = total_wins / total_losses if total_losses > 0 else 0

            results.append({
                'indicator': indicator_name,
                'total_trades': total_trades,
                'win_rate': round(win_rate, 2),
                'total_pnl': round(stats['total_pnl'], 2),
                'avg_pnl': round(avg_pnl, 4),
                'wins': stats['wins'],
                'losses': stats['losses'],
                'profit_factor': round(profit_factor, 2)
            })

        # Sort by total P/L descending
        results.sort(key=lambda x: x['total_pnl'], reverse=True)

        return results

    def get_pattern_performance(self) -> List[Dict]:
        """Analyze performance of all pattern recognitions over last N days"""

        start_date = datetime.utcnow() - timedelta(days=self.days_back)

        # Query all closed trades with signal info
        trades = self.session.query(Trade, TradingSignal).join(
            TradingSignal,
            Trade.signal_id == TradingSignal.id
        ).filter(
            and_(
                Trade.created_at >= start_date,
                Trade.status.in_(['closed', 'completed']),
                TradingSignal.patterns_detected.isnot(None)
            )
        ).all()

        if not trades:
            logger.warning(f"No trades with patterns found in last {self.days_back} days")
            return []

        # Aggregate by pattern
        pattern_stats = defaultdict(lambda: {
            'trades': [],
            'total_pnl': 0,
            'wins': 0,
            'losses': 0,
            'total_trades': 0
        })

        for trade, signal in trades:
            if not signal.patterns_detected:
                continue

            # Each trade can have multiple patterns
            for pattern_name in signal.patterns_detected:
                stats = pattern_stats[pattern_name]
                stats['trades'].append(trade)
                stats['total_trades'] += 1

                pnl = float(trade.profit) if trade.profit else 0
                stats['total_pnl'] += pnl

                if pnl > 0:
                    stats['wins'] += 1
                elif pnl < 0:
                    stats['losses'] += 1

        # Calculate metrics
        results = []
        for pattern_name, stats in pattern_stats.items():
            total_trades = stats['total_trades']
            if total_trades == 0:
                continue

            win_rate = (stats['wins'] / total_trades * 100) if total_trades > 0 else 0
            avg_pnl = stats['total_pnl'] / total_trades

            # Calculate profit factor
            winning_trades = [t for t in stats['trades'] if t.profit and float(t.profit) > 0]
            losing_trades = [t for t in stats['trades'] if t.profit and float(t.profit) < 0]

            total_wins = sum(float(t.profit) for t in winning_trades if t.profit)
            total_losses = abs(sum(float(t.profit) for t in losing_trades if t.profit))

            profit_factor = total_wins / total_losses if total_losses > 0 else 0

            results.append({
                'pattern': pattern_name,
                'total_trades': total_trades,
                'win_rate': round(win_rate, 2),
                'total_pnl': round(stats['total_pnl'], 2),
                'avg_pnl': round(avg_pnl, 4),
                'wins': stats['wins'],
                'losses': stats['losses'],
                'profit_factor': round(profit_factor, 2)
            })

        # Sort by total P/L descending
        results.sort(key=lambda x: x['total_pnl'], reverse=True)

        return results

    def send_telegram_report(
        self,
        top_indicators: List[Dict],
        top_patterns: List[Dict]
    ) -> bool:
        """Send Top 10 report via Telegram"""

        if not self.telegram.enabled:
            logger.warning("Telegram not enabled - skipping notification")
            return False

        now = datetime.utcnow()

        # Build message
        message = f"""🏆 <b>TOP PERFORMERS</b> - Last {self.days_back} Days
{now.strftime('%d.%m.%Y')}

<b>🎯 TOP 5 INDICATORS:</b>"""

        # Add top 5 indicators
        for i, ind in enumerate(top_indicators[:5], 1):
            emoji = '✅' if ind['total_pnl'] > 0 else '❌'
            message += f"\n{i}. {emoji} <b>{ind['indicator']}</b>"
            message += f"\n   €{ind['total_pnl']:+.2f} | {ind['win_rate']:.0f}% WR | {ind['total_trades']}T"

        message += f"\n\n<b>📊 TOP 5 PATTERNS:</b>"

        # Add top 5 patterns
        for i, pat in enumerate(top_patterns[:5], 1):
            emoji = '✅' if pat['total_pnl'] > 0 else '❌'
            message += f"\n{i}. {emoji} <b>{pat['pattern']}</b>"
            message += f"\n   €{pat['total_pnl']:+.2f} | {pat['win_rate']:.0f}% WR | {pat['total_trades']}T"

        message += f"\n\n<i>Full report: ai_analysis_reports/top_performers_{now.strftime('%Y%m%d')}.json</i>"

        try:
            return self.telegram.send_message(message, silent=True)
        except Exception as e:
            logger.error(f"Error sending Telegram notification: {e}")
            return False

    def save_ai_report(
        self,
        top_indicators: List[Dict],
        top_patterns: List[Dict]
    ) -> str:
        """Save detailed top performers report for AI access"""

        now = datetime.utcnow()
        filename = f"top_performers_{now.strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(self.ai_reports_dir, filename)

        # Build comprehensive report for AI
        ai_report = {
            'report_metadata': {
                'generated_at': now.isoformat(),
                'report_type': 'top_performers',
                'lookback_days': self.days_back,
                'analysis_period': {
                    'start': (now - timedelta(days=self.days_back)).isoformat(),
                    'end': now.isoformat()
                }
            },
            'top_10_indicators': top_indicators[:10],
            'top_10_patterns': top_patterns[:10],
            'all_indicators': top_indicators,
            'all_patterns': top_patterns,
            'summary': {
                'total_indicators_analyzed': len(top_indicators),
                'total_patterns_analyzed': len(top_patterns),
                'best_indicator': top_indicators[0] if top_indicators else None,
                'best_pattern': top_patterns[0] if top_patterns else None,
                'worst_indicator': top_indicators[-1] if top_indicators else None,
                'worst_pattern': top_patterns[-1] if top_patterns else None
            },
            'ai_insights': {
                'profitable_indicators': len([i for i in top_indicators if i['total_pnl'] > 0]),
                'profitable_patterns': len([p for p in top_patterns if p['total_pnl'] > 0]),
                'high_wr_indicators': [i for i in top_indicators if i['win_rate'] >= 60][:5],
                'high_wr_patterns': [p for p in top_patterns if p['win_rate'] >= 60][:5],
                'indicators_to_disable': [i for i in top_indicators if i['win_rate'] < 35 and i['total_trades'] >= 20],
                'patterns_to_disable': [p for p in top_patterns if p['win_rate'] < 35 and p['total_trades'] >= 20]
            }
        }

        # Save to file
        try:
            with open(filepath, 'w') as f:
                json.dump(ai_report, f, indent=2, default=str)

            logger.info(f"✅ AI top performers report saved: {filepath}")

            # Also save a "latest.json" for easy AI access
            latest_path = os.path.join(self.ai_reports_dir, 'latest_top_performers.json')
            with open(latest_path, 'w') as f:
                json.dump(ai_report, f, indent=2, default=str)

            return filepath

        except Exception as e:
            logger.error(f"Error saving AI report: {e}")
            return None

    def generate_report(self) -> bool:
        """Generate complete top performers report"""

        logger.info(f"Analyzing top performers for last {self.days_back} days...")

        # Get indicator performance
        top_indicators = self.get_indicator_performance()
        logger.info(f"✅ Analyzed {len(top_indicators)} indicators")

        # Get pattern performance
        top_patterns = self.get_pattern_performance()
        logger.info(f"✅ Analyzed {len(top_patterns)} patterns")

        if not top_indicators and not top_patterns:
            logger.warning("No data available for analysis")
            return False

        # Display top 10 indicators
        if top_indicators:
            logger.info("\n" + "="*60)
            logger.info("TOP 10 INDICATORS (by Total P/L):")
            logger.info("="*60)
            for i, ind in enumerate(top_indicators[:10], 1):
                logger.info(
                    f"{i:2d}. {ind['indicator']:30s} | "
                    f"€{ind['total_pnl']:+8.2f} | "
                    f"{ind['win_rate']:5.1f}% WR | "
                    f"{ind['total_trades']:3d}T | "
                    f"PF: {ind['profit_factor']:.2f}"
                )

        # Display top 10 patterns
        if top_patterns:
            logger.info("\n" + "="*60)
            logger.info("TOP 10 PATTERNS (by Total P/L):")
            logger.info("="*60)
            for i, pat in enumerate(top_patterns[:10], 1):
                logger.info(
                    f"{i:2d}. {pat['pattern']:30s} | "
                    f"€{pat['total_pnl']:+8.2f} | "
                    f"{pat['win_rate']:5.1f}% WR | "
                    f"{pat['total_trades']:3d}T | "
                    f"PF: {pat['profit_factor']:.2f}"
                )

        # Send Telegram notification
        telegram_sent = self.send_telegram_report(top_indicators, top_patterns)
        if telegram_sent:
            logger.info("✅ Telegram notification sent")
        else:
            logger.warning("⚠️  Telegram notification not sent")

        # Save AI-accessible report
        ai_report_path = self.save_ai_report(top_indicators, top_patterns)
        if ai_report_path:
            logger.info(f"✅ AI report saved: {ai_report_path}")

        return True


def main():
    """Main entry point"""

    import argparse

    parser = argparse.ArgumentParser(description='Analyze top performing indicators and patterns')
    parser.add_argument('--days', type=int, default=14, help='Number of days to analyze (default: 14)')
    args = parser.parse_args()

    analyzer = TopPerformersAnalyzer(days_back=args.days)

    try:
        success = analyzer.generate_report()
        return 0 if success else 1
    except Exception as e:
        logger.error(f"Error generating top performers report: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
