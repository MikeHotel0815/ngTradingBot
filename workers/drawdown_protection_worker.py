#!/usr/bin/env python3
"""
Emergency Drawdown Protection Worker

Monitors account-level risk and implements emergency stops to protect capital.

Critical Safety Features:
1. Daily Drawdown Limit - Pauses trading if daily loss exceeds threshold
2. Account Emergency Stop - Force closes all trades if total loss exceeds critical threshold
3. Correlation Filter - Prevents over-exposure to single currency/asset
4. Position Limit - Maximum open trades per symbol/timeframe

Part of Phase 6: Safety & Risk Management
See: AUTONOMOUS_TRADING_ROADMAP.md
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Set
from collections import defaultdict
import uuid

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from models import Trade, Command, GlobalSettings

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://trader:tradingbot_secret_2025@postgres:5432/ngtradingbot')
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

# Configuration
DRAWDOWN_PROTECTION_ENABLED = os.getenv('DRAWDOWN_PROTECTION_ENABLED', 'true').lower() == 'true'
CHECK_INTERVAL_SECONDS = int(os.getenv('DRAWDOWN_CHECK_INTERVAL', '60'))  # Check every minute

# Drawdown Limits
DAILY_LOSS_LIMIT = float(os.getenv('DAILY_LOSS_LIMIT', '-30.0'))  # EUR
ACCOUNT_EMERGENCY_LIMIT = float(os.getenv('ACCOUNT_EMERGENCY_LIMIT', '-50.0'))  # EUR
DAILY_LOSS_WARNING = float(os.getenv('DAILY_LOSS_WARNING', '-20.0'))  # EUR - Warning threshold

# Correlation Limits
MAX_POSITIONS_SAME_CURRENCY = int(os.getenv('MAX_POSITIONS_SAME_CURRENCY', '2'))  # Max 2 USD pairs
MAX_POSITIONS_PER_SYMBOL = int(os.getenv('MAX_POSITIONS_PER_SYMBOL', '1'))  # Max 1 per symbol
MAX_TOTAL_OPEN_POSITIONS = int(os.getenv('MAX_TOTAL_OPEN_POSITIONS', '5'))  # Max 5 total

# Currency Correlation Groups
CURRENCY_GROUPS = {
    'USD': ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD', 'NZDUSD', 'XAUUSD'],
    'EUR': ['EURUSD', 'EURGBP', 'EURJPY', 'EURCHF', 'EURCAD', 'EURAUD'],
    'GBP': ['GBPUSD', 'EURGBP', 'GBPJPY', 'GBPCHF', 'GBPCAD', 'GBPAUD'],
    'JPY': ['USDJPY', 'EURJPY', 'GBPJPY', 'CHFJPY', 'CADJPY', 'AUDJPY'],
}


def get_today_trades_pnl(db: Session, account_id: int) -> Dict:
    """
    Calculate today's realized + unrealized P&L

    Returns:
        {
            'realized_pnl': float,  # Closed trades today
            'unrealized_pnl': float,  # Open trades current profit
            'total_pnl': float,  # Combined
            'closed_count': int,
            'open_count': int
        }
    """
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Get realized P&L from closed trades today
    result = db.execute(text("""
        SELECT
            COALESCE(SUM(profit), 0) as realized_pnl,
            COUNT(*) as closed_count
        FROM trades
        WHERE account_id = :account_id
        AND close_time >= :today_start
        AND status = 'closed'
    """), {'account_id': account_id, 'today_start': today_start})

    row = result.fetchone()
    realized_pnl = float(row.realized_pnl) if row.realized_pnl else 0.0
    closed_count = int(row.closed_count) if row.closed_count else 0

    # Get unrealized P&L from open trades
    result = db.execute(text("""
        SELECT
            COALESCE(SUM(profit), 0) as unrealized_pnl,
            COUNT(*) as open_count
        FROM trades
        WHERE account_id = :account_id
        AND status = 'open'
    """), {'account_id': account_id})

    row = result.fetchone()
    unrealized_pnl = float(row.unrealized_pnl) if row.unrealized_pnl else 0.0
    open_count = int(row.open_count) if row.open_count else 0

    total_pnl = realized_pnl + unrealized_pnl

    return {
        'realized_pnl': realized_pnl,
        'unrealized_pnl': unrealized_pnl,
        'total_pnl': total_pnl,
        'closed_count': closed_count,
        'open_count': open_count
    }


def get_account_total_pnl(db: Session, account_id: int) -> float:
    """Get total account P&L (all time, open + closed)"""
    result = db.execute(text("""
        SELECT COALESCE(SUM(profit), 0) as total_pnl
        FROM trades
        WHERE account_id = :account_id
    """), {'account_id': account_id})

    row = result.fetchone()
    return float(row.total_pnl) if row.total_pnl else 0.0


def check_daily_drawdown_limit(db: Session, account_id: int) -> tuple[bool, str, Dict]:
    """
    Check if daily loss limit exceeded

    Returns:
        (limit_exceeded, action_required, pnl_data)
    """
    pnl_data = get_today_trades_pnl(db, account_id)
    total_today = pnl_data['total_pnl']

    # Check warning threshold
    if total_today <= DAILY_LOSS_WARNING and total_today > DAILY_LOSS_LIMIT:
        return False, 'warning', pnl_data

    # Check critical threshold
    if total_today <= DAILY_LOSS_LIMIT:
        return True, 'pause_trading', pnl_data

    return False, 'ok', pnl_data


def check_account_emergency_limit(db: Session, account_id: int) -> tuple[bool, str, float]:
    """
    Check if account emergency limit exceeded

    Returns:
        (limit_exceeded, action_required, total_pnl)
    """
    # Get open trades P&L (emergency is based on current drawdown)
    result = db.execute(text("""
        SELECT COALESCE(SUM(profit), 0) as unrealized_pnl
        FROM trades
        WHERE account_id = :account_id
        AND status = 'open'
    """), {'account_id': account_id})

    row = result.fetchone()
    unrealized_pnl = float(row.unrealized_pnl) if row.unrealized_pnl else 0.0

    if unrealized_pnl <= ACCOUNT_EMERGENCY_LIMIT:
        return True, 'emergency_close_all', unrealized_pnl

    return False, 'ok', unrealized_pnl


def get_currency_exposure(db: Session, account_id: int) -> Dict[str, List[Trade]]:
    """
    Get current currency exposure

    Returns:
        {
            'USD': [trade1, trade2, ...],
            'EUR': [trade3, ...],
            ...
        }
    """
    open_trades = db.query(Trade).filter_by(
        account_id=account_id,
        status='open'
    ).all()

    exposure = defaultdict(list)

    for trade in open_trades:
        symbol = trade.symbol.upper()

        # Find which currency groups this symbol belongs to
        for currency, symbols in CURRENCY_GROUPS.items():
            if symbol in symbols:
                exposure[currency].append(trade)

    return dict(exposure)


def check_correlation_limits(db: Session, account_id: int) -> tuple[bool, str, Dict]:
    """
    Check if correlation limits exceeded

    Returns:
        (limit_exceeded, reason, exposure_data)
    """
    exposure = get_currency_exposure(db, account_id)

    # Check per-currency limit
    for currency, trades in exposure.items():
        if len(trades) > MAX_POSITIONS_SAME_CURRENCY:
            return True, f'too_many_{currency}_positions', exposure

    # Check per-symbol limit
    symbol_counts = defaultdict(int)
    open_trades = db.query(Trade).filter_by(
        account_id=account_id,
        status='open'
    ).all()

    for trade in open_trades:
        symbol_counts[trade.symbol] += 1

    for symbol, count in symbol_counts.items():
        if count > MAX_POSITIONS_PER_SYMBOL:
            return True, f'too_many_{symbol}_trades', exposure

    # Check total position limit
    total_positions = len(open_trades)
    if total_positions > MAX_TOTAL_OPEN_POSITIONS:
        return True, 'too_many_total_positions', exposure

    return False, 'ok', exposure


def create_close_all_command(db: Session, account_id: int, reason: str) -> int:
    """Create CLOSE_TRADE commands for all open trades"""
    open_trades = db.query(Trade).filter_by(
        account_id=account_id,
        status='open'
    ).all()

    closed_count = 0

    for trade in open_trades:
        try:
            command_id = str(uuid.uuid4())

            payload_data = {
                'ticket': int(trade.ticket),
                'reason': f'emergency_{reason}',
                'worker': 'drawdown_protection_worker'
            }

            command = Command(
                id=command_id,
                account_id=account_id,
                command_type='CLOSE_TRADE',
                payload=payload_data,
                status='pending',
                created_at=datetime.utcnow()
            )

            db.add(command)
            closed_count += 1

        except Exception as e:
            logger.error(f"Error creating close command for trade {trade.ticket}: {e}")
            continue

    db.commit()
    return closed_count


def pause_auto_trading(db: Session, account_id: int, reason: str):
    """Pause auto-trading by updating global settings"""
    try:
        settings = GlobalSettings.get_settings(db)

        # Store pause reason and timestamp
        db.execute(text("""
            INSERT INTO daily_drawdown_limits (account_id, date, reason, paused_at)
            VALUES (:account_id, :date, :reason, :paused_at)
            ON CONFLICT (account_id, date) DO UPDATE
            SET reason = :reason, paused_at = :paused_at
        """), {
            'account_id': account_id,
            'date': datetime.utcnow().date(),
            'reason': reason,
            'paused_at': datetime.utcnow()
        })

        db.commit()

        logger.warning(f"⏸️  AUTO-TRADING PAUSED: {reason}")

    except Exception as e:
        logger.error(f"Error pausing auto-trading: {e}")
        db.rollback()


def check_drawdown_protection(db: Session, account_id: int) -> Dict:
    """Main drawdown protection check"""

    stats = {
        'daily_limit_ok': True,
        'account_limit_ok': True,
        'correlation_ok': True,
        'action_taken': None,
        'pnl_data': {}
    }

    # 1. Check Account Emergency Limit (MOST CRITICAL)
    emergency_exceeded, emergency_action, unrealized_pnl = check_account_emergency_limit(db, account_id)

    if emergency_exceeded:
        logger.critical(
            f"🚨 ACCOUNT EMERGENCY LIMIT EXCEEDED! "
            f"Unrealized P&L: {unrealized_pnl:.2f} EUR <= {ACCOUNT_EMERGENCY_LIMIT} EUR"
        )

        # FORCE CLOSE ALL TRADES
        closed_count = create_close_all_command(db, account_id, 'account_emergency')

        logger.critical(f"🚨 EMERGENCY: Created {closed_count} CLOSE commands (ALL TRADES)")

        # Pause auto-trading
        pause_auto_trading(db, account_id, f'account_emergency_{ACCOUNT_EMERGENCY_LIMIT}')

        stats['account_limit_ok'] = False
        stats['action_taken'] = 'emergency_close_all'
        stats['pnl_data']['unrealized_pnl'] = unrealized_pnl

        return stats

    # 2. Check Daily Drawdown Limit
    daily_exceeded, daily_action, pnl_data = check_daily_drawdown_limit(db, account_id)

    stats['pnl_data'] = pnl_data

    if daily_action == 'warning':
        logger.warning(
            f"⚠️  DAILY LOSS WARNING: {pnl_data['total_pnl']:.2f} EUR "
            f"(threshold: {DAILY_LOSS_WARNING} EUR)"
        )

    if daily_exceeded:
        logger.error(
            f"🛑 DAILY LOSS LIMIT EXCEEDED! "
            f"Today's P&L: {pnl_data['total_pnl']:.2f} EUR <= {DAILY_LOSS_LIMIT} EUR"
        )

        # Pause auto-trading (but don't close existing trades)
        pause_auto_trading(db, account_id, f'daily_limit_{DAILY_LOSS_LIMIT}')

        stats['daily_limit_ok'] = False
        stats['action_taken'] = 'pause_trading'

        return stats

    # 3. Check Correlation Limits
    correlation_exceeded, correlation_reason, exposure = check_correlation_limits(db, account_id)

    if correlation_exceeded:
        logger.warning(
            f"⚠️  CORRELATION LIMIT EXCEEDED: {correlation_reason}"
        )

        stats['correlation_ok'] = False
        stats['action_taken'] = 'correlation_warning'

    return stats


def run_worker():
    """Main worker loop"""
    logger.info("=" * 80)
    logger.info("EMERGENCY DRAWDOWN PROTECTION WORKER STARTING")
    logger.info("=" * 80)
    logger.info(f"Enabled: {DRAWDOWN_PROTECTION_ENABLED}")
    logger.info(f"Check Interval: {CHECK_INTERVAL_SECONDS}s")
    logger.info("")
    logger.info("🛡️  PROTECTION LEVELS:")
    logger.info(f"  Daily Loss Warning: {DAILY_LOSS_WARNING} EUR")
    logger.info(f"  Daily Loss Limit: {DAILY_LOSS_LIMIT} EUR (pause trading)")
    logger.info(f"  Account Emergency: {ACCOUNT_EMERGENCY_LIMIT} EUR (close all)")
    logger.info("")
    logger.info("🔒 CORRELATION LIMITS:")
    logger.info(f"  Max positions same currency: {MAX_POSITIONS_SAME_CURRENCY}")
    logger.info(f"  Max positions per symbol: {MAX_POSITIONS_PER_SYMBOL}")
    logger.info(f"  Max total open positions: {MAX_TOTAL_OPEN_POSITIONS}")
    logger.info("=" * 80)

    if not DRAWDOWN_PROTECTION_ENABLED:
        logger.warning("⚠️  DRAWDOWN_PROTECTION_ENABLED=false - Worker running in monitoring mode only")

    iteration = 0

    while True:
        try:
            iteration += 1
            logger.info(f"\n--- Iteration {iteration} - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC ---")

            db = SessionLocal()
            try:
                # Get first account (assume single account for now)
                result = db.execute(text("SELECT id FROM accounts LIMIT 1"))
                row = result.fetchone()

                if not row:
                    logger.warning("No accounts found in database")
                    time.sleep(CHECK_INTERVAL_SECONDS)
                    continue

                account_id = row.id

                # Run protection checks
                if DRAWDOWN_PROTECTION_ENABLED:
                    stats = check_drawdown_protection(db, account_id)

                    # Log status
                    pnl = stats['pnl_data']
                    logger.info(
                        f"📊 Status: Daily P&L: {pnl.get('total_pnl', 0):.2f} EUR "
                        f"({pnl.get('closed_count', 0)} closed, {pnl.get('open_count', 0)} open) | "
                        f"Action: {stats['action_taken'] or 'None'}"
                    )
                else:
                    # Monitoring only
                    pnl_data = get_today_trades_pnl(db, account_id)
                    logger.info(
                        f"📊 Monitor: Daily P&L: {pnl_data['total_pnl']:.2f} EUR "
                        f"({pnl_data['closed_count']} closed, {pnl_data['open_count']} open)"
                    )

            finally:
                db.close()

            # Sleep until next check
            time.sleep(CHECK_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logger.info("\n⚠️  Shutdown signal received - stopping worker")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
            time.sleep(60)


if __name__ == '__main__':
    try:
        run_worker()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
