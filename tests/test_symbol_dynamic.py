#!/usr/bin/env python3
"""
Test Script for Symbol Dynamic Manager
Simulates updating configs based on recent trades
"""

import sys
from database import ScopedSession
from models import Trade
from symbol_dynamic_manager import SymbolDynamicManager
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_update_from_recent_trades():
    """Test updating symbol configs based on recent closed trades"""
    db = ScopedSession()
    manager = SymbolDynamicManager(account_id=1)

    try:
        # Get recent closed trades
        recent_trades = db.query(Trade).filter(
            Trade.account_id == 1,
            Trade.status == 'closed',
            Trade.profit != None
        ).order_by(Trade.close_time.desc()).limit(20).all()

        logger.info(f"Found {len(recent_trades)} recent closed trades")

        if not recent_trades:
            logger.warning("No closed trades found. Nothing to update.")
            return

        # Group trades by symbol
        by_symbol = {}
        for trade in recent_trades:
            key = (trade.symbol, trade.direction.upper())
            if key not in by_symbol:
                by_symbol[key] = []
            by_symbol[key].append(trade)

        logger.info(f"Grouped into {len(by_symbol)} symbol+direction combinations")

        # Update each symbol's config
        for (symbol, direction), trades in by_symbol.items():
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing {symbol} {direction} ({len(trades)} trades)")
            logger.info(f"{'='*60}")

            # Update config based on last trade (as if it just closed)
            last_trade = trades[0]  # Most recent
            config = manager.update_after_trade(db, last_trade, market_regime='RANGING')

            logger.info(f"\nFinal Config:")
            logger.info(f"  Status: {config.status}")
            logger.info(f"  Min Confidence: {config.min_confidence_threshold}%")
            logger.info(f"  Risk Multiplier: {config.risk_multiplier}x")
            logger.info(f"  Rolling: {config.rolling_winrate}% ({config.rolling_wins}W/{config.rolling_losses}L)")
            logger.info(f"  Consecutive: {config.consecutive_wins}W / {config.consecutive_losses}L")

        logger.info(f"\n{'='*60}")
        logger.info("Summary of all configs:")
        logger.info(f"{'='*60}")

        all_configs = manager.get_all_configs(db)
        for config in all_configs:
            if config.rolling_trades_count > 0:
                logger.info(
                    f"{config.symbol:8s} {config.direction or 'BOTH':4s} | "
                    f"Status: {config.status:12s} | "
                    f"Conf≥{config.min_confidence_threshold:5.1f}% | "
                    f"Risk={config.risk_multiplier:4.2f}x | "
                    f"WR={config.rolling_winrate or 0:5.1f}% | "
                    f"P/L={config.rolling_profit or 0:7.2f}"
                )

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


if __name__ == '__main__':
    logger.info("Testing Symbol Dynamic Manager")
    test_update_from_recent_trades()
    logger.info("\nTest completed!")
