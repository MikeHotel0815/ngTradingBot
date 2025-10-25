#!/usr/bin/env python3
"""
Seed Initial Heiken Ashi Parameter Versions
Imports current parameters from heiken_ashi_config.py and creates database records
"""

import os
import sys
import logging
from decimal import Decimal
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from parameter_versioning_models import IndicatorParameterVersion
from heiken_ashi_config import HEIKEN_ASHI_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def seed_initial_parameters():
    """Seed database with initial parameter versions from config file"""

    session = SessionLocal()

    indicator_name = 'HEIKEN_ASHI_TREND'
    created_count = 0

    for symbol, symbol_config in HEIKEN_ASHI_CONFIG.items():
        if not symbol_config.get('enabled'):
            logger.info(f"Skipping {symbol} (disabled)")
            continue

        timeframes = symbol_config.get('timeframes', {})

        for timeframe, tf_config in timeframes.items():
            if not tf_config.get('enabled'):
                logger.info(f"Skipping {symbol} {timeframe} (disabled)")
                continue

            # Check if version already exists
            existing = session.query(IndicatorParameterVersion).filter_by(
                indicator_name=indicator_name,
                symbol=symbol,
                timeframe=timeframe,
                status='active'
            ).first()

            if existing:
                logger.info(f"✓ {symbol} {timeframe} already exists (version {existing.version})")
                continue

            # Extract parameters from config
            parameters = {
                'min_confidence': tf_config.get('min_confidence', 60),
                'sl_multiplier': tf_config.get('sl_multiplier', 1.5),
                'tp_multiplier': tf_config.get('tp_multiplier', 3.0),
                'priority': tf_config.get('priority', 'MEDIUM'),
                'enabled': tf_config.get('enabled', True)
            }

            # Get backtest metrics if available from notes/comments
            # For initial seed, we'll use the 30-day backtest results as baseline
            backtest_notes = tf_config.get('notes', '')

            # Parse backtest metrics from notes (format: "42.0% WR, +23.74%")
            backtest_wr = None
            backtest_pnl = None
            backtest_trades = None

            if '%' in backtest_notes:
                import re
                # Extract win rate
                wr_match = re.search(r'(\d+\.\d+)% WR', backtest_notes)
                if wr_match:
                    backtest_wr = Decimal(wr_match.group(1))

                # Extract P/L
                pnl_match = re.search(r'([+-]?\d+\.\d+)%', backtest_notes)
                if pnl_match:
                    # This is P/L percentage - we don't have absolute EUR value from notes
                    # We'll leave backtest_pnl as None for now
                    pass

                # Extract trades if available
                trades_match = re.search(r'(\d+) trades', backtest_notes.lower())
                if trades_match:
                    backtest_trades = int(trades_match.group(1))

            # Create initial version (v1)
            version = IndicatorParameterVersion(
                indicator_name=indicator_name,
                symbol=symbol,
                timeframe=timeframe,
                version=1,
                parameters=parameters,
                backtest_win_rate=backtest_wr,
                backtest_total_pnl=backtest_pnl,
                backtest_avg_pnl=None,
                backtest_trades=backtest_trades,
                backtest_period_days=30,  # Based on 30-day backtest
                status='active',
                approved_by='system',
                approved_at=datetime.utcnow(),
                activated_at=datetime.utcnow(),
                created_by='seed_script',
                notes=f"Initial parameters from heiken_ashi_config.py - {backtest_notes}"
            )

            session.add(version)
            created_count += 1

            logger.info(f"✅ Created {symbol} {timeframe} v1 (WR: {backtest_wr}%)")

    session.commit()

    logger.info(f"\n{'='*60}")
    logger.info(f"✅ Seeding complete: {created_count} parameter versions created")
    logger.info(f"{'='*60}\n")

    return created_count


def main():
    """Main entry point"""

    try:
        count = seed_initial_parameters()
        print(f"✅ Successfully seeded {count} Heiken Ashi parameter versions")
        return 0
    except Exception as e:
        logger.error(f"Error seeding parameters: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
