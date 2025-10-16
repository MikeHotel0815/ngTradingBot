#!/usr/bin/env python3
"""
Test Micro-Trailing Stop Manager
Apply to trade #16448948
"""

import sys
import os

# Set DATABASE_URL before importing
os.environ['DATABASE_URL'] = 'postgresql://trader:tradingbot_secret_2025@postgres:5432/ngtradingbot'

from database import ScopedSession
from models import Trade, Tick
from micro_trailing_manager import MicroTrailingManager
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_specific_trade(ticket: int):
    """Test micro-trailing on specific trade"""
    db = ScopedSession()
    manager = MicroTrailingManager()

    try:
        # Get the trade
        trade = db.query(Trade).filter_by(ticket=ticket).first()

        if not trade:
            logger.error(f"Trade #{ticket} not found")
            return

        logger.info(f"\n{'='*60}")
        logger.info(f"Testing Micro-Trailing on Trade #{ticket}")
        logger.info(f"{'='*60}")
        logger.info(f"Symbol: {trade.symbol}")
        logger.info(f"Direction: {trade.direction}")
        logger.info(f"Entry: {trade.open_price}")
        logger.info(f"Current SL: {trade.sl}")
        logger.info(f"Current TP: {trade.tp}")
        logger.info(f"Volume: {trade.volume}")
        logger.info(f"Status: {trade.status}")

        # Get current price from latest tick
        latest_tick = db.query(Tick).filter_by(
            account_id=trade.account_id,
            symbol=trade.symbol
        ).order_by(Tick.timestamp.desc()).first()

        if not latest_tick:
            logger.error(f"No tick data for {trade.symbol}")
            return

        # Use bid for BUY (closing at bid), ask for SELL (closing at ask)
        is_buy = trade.direction.upper() in ['BUY', 'BUY', '0']
        current_price = float(latest_tick.bid if is_buy else latest_tick.ask)

        logger.info(f"Current Price: {current_price}")

        # Calculate profit
        entry_price = float(trade.open_price)
        if is_buy:
            profit_distance = current_price - entry_price
        else:
            profit_distance = entry_price - current_price

        logger.info(f"Profit Distance: {profit_distance:.2f} points")

        # Get micro-trailing config
        config = manager.get_config(trade.symbol)
        logger.info(f"\nMicro-Trailing Config for {trade.symbol}:")
        logger.info(f"  Min Profit to Start: {config['min_profit_to_start']} points")
        logger.info(f"  Trailing Step: {config['trailing_step_points']} points")
        logger.info(f"  Trailing Distance: {config['trailing_distance_points']} points")
        logger.info(f"  Point Value: {config['point_value']}")

        # Calculate new SL
        result = manager.calculate_micro_trailing_stop(trade, current_price, db)

        if result:
            logger.info(f"\n✅ MICRO-TRAILING TRIGGERED:")
            logger.info(f"  Old SL: {trade.sl}")
            logger.info(f"  New SL: {result['new_sl']}")
            logger.info(f"  Reason: {result['reason']}")
            logger.info(f"  Protected Profit: {result.get('protected_profit', 0):.2f} points")

            # Ask for confirmation
            response = input("\n⚠️  Apply this micro-trailing adjustment? (yes/no): ")

            if response.lower() == 'yes':
                success = manager.send_sl_modify_command(
                    db=db,
                    trade=trade,
                    new_sl=result['new_sl'],
                    reason=result['reason']
                )

                if success:
                    logger.info("✅ Command sent successfully!")
                else:
                    logger.error("❌ Failed to send command")
            else:
                logger.info("❌ Micro-trailing adjustment cancelled")

        else:
            logger.info(f"\n❌ No micro-trailing adjustment needed")
            logger.info(f"  Reason: Conditions not met")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


def test_all_trades():
    """Test micro-trailing on all open trades"""
    db = ScopedSession()
    manager = MicroTrailingManager()

    try:
        logger.info(f"\n{'='*60}")
        logger.info("Testing Micro-Trailing on All Open Trades")
        logger.info(f"{'='*60}\n")

        stats = manager.process_all_open_trades(db)

        logger.info(f"\n{'='*60}")
        logger.info("Results:")
        logger.info(f"  Total Trades: {stats['total_trades']}")
        logger.info(f"  Trailed: {stats['trailed']}")
        logger.info(f"  Errors: {stats['errors']}")
        logger.info(f"{'='*60}")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'all':
        test_all_trades()
    elif len(sys.argv) > 1:
        ticket = int(sys.argv[1])
        test_specific_trade(ticket)
    else:
        logger.info("Usage:")
        logger.info("  python test_micro_trailing.py 16448948     # Test specific trade")
        logger.info("  python test_micro_trailing.py all           # Test all open trades")
        logger.info("")
        logger.info("Testing trade #16448948 by default...")
        test_specific_trade(16448948)
