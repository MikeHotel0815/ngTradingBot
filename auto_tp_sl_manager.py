"""
Auto TP/SL Manager

Automatically sets TP/SL for manual MT5 trades that don't have them.
Runs during heartbeat processing to detect trades without protection.

Features:
- Detects trades with SL=0 or TP=0
- Calculates Smart TP/SL using SmartTPSL class
- Sends MODIFY_POSITION command to MT5
- Logs all actions for transparency
"""

import logging
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from models import Trade
from smart_tp_sl import get_smart_tp_sl
from database import ScopedSession
import uuid

logger = logging.getLogger(__name__)


class AutoTPSLManager:
    """Manages automatic TP/SL setting for manual MT5 trades"""

    def __init__(self):
        self.processed_tickets = set()  # Track processed tickets to avoid duplicates

    def check_and_set_tp_sl(self, account_id: int, db: Optional[Session] = None) -> Dict:
        """
        Check all open trades for missing TP/SL and set them automatically.

        Args:
            account_id: Account ID to check
            db: Database session (optional)

        Returns:
            Dict with statistics about processed trades
        """
        close_db = False
        if db is None:
            db = ScopedSession()
            close_db = True

        try:
            stats = {
                'checked': 0,
                'found_without_tpsl': 0,
                'successfully_set': 0,
                'failed': 0,
                'skipped': 0,
                'trades_processed': []
            }

            # Get all open trades for this account
            open_trades = db.query(Trade).filter(
                Trade.account_id == account_id,
                Trade.status == 'open'
            ).all()

            stats['checked'] = len(open_trades)

            for trade in open_trades:
                # Skip if already processed in this session
                if trade.ticket in self.processed_tickets:
                    stats['skipped'] += 1
                    continue

                # Check if SL or TP is missing (0 or None)
                sl_missing = trade.sl is None or float(trade.sl) == 0.0
                tp_missing = trade.tp is None or float(trade.tp) == 0.0

                if sl_missing or tp_missing:
                    stats['found_without_tpsl'] += 1

                    logger.info(
                        f"🎯 Auto TP/SL: Found trade without protection - "
                        f"#{trade.ticket} {trade.symbol} {trade.direction} "
                        f"(SL: {trade.sl}, TP: {trade.tp})"
                    )

                    # Calculate Smart TP/SL
                    result = self._calculate_and_set_tp_sl(trade, db)

                    if result['success']:
                        stats['successfully_set'] += 1
                        stats['trades_processed'].append({
                            'ticket': trade.ticket,
                            'symbol': trade.symbol,
                            'sl': result['sl'],
                            'tp': result['tp'],
                            'reason': result.get('reason', 'Auto-set')
                        })
                        # Mark as processed
                        self.processed_tickets.add(trade.ticket)
                    else:
                        stats['failed'] += 1
                        logger.error(
                            f"❌ Auto TP/SL: Failed for #{trade.ticket} - {result.get('error')}"
                        )

            if stats['successfully_set'] > 0:
                logger.info(
                    f"✅ Auto TP/SL Summary: Set TP/SL for {stats['successfully_set']}/{stats['found_without_tpsl']} "
                    f"trades (checked {stats['checked']} total)"
                )

            return stats

        except Exception as e:
            logger.error(f"Error in auto TP/SL check: {e}", exc_info=True)
            return {'error': str(e)}
        finally:
            if close_db:
                db.close()

    def _calculate_and_set_tp_sl(self, trade: Trade, db: Session) -> Dict:
        """
        Calculate Smart TP/SL for a trade and set it in DB + send command to MT5.

        Args:
            trade: Trade object
            db: Database session

        Returns:
            Dict with success status and calculated values
        """
        try:
            symbol = trade.symbol
            direction = trade.direction.lower() if isinstance(trade.direction, str) else ('buy' if trade.direction == 0 else 'sell')
            entry_price = float(trade.open_price)

            # Detect timeframe based on trade age or default to H4
            timeframe = self._detect_timeframe(trade)

            logger.info(
                f"🔄 Calculating Smart TP/SL for #{trade.ticket} "
                f"{symbol} {direction.upper()} @ {entry_price:.5f} ({timeframe})"
            )

            # Calculate using SmartTPSLCalculator
            calculator = get_smart_tp_sl(trade.account_id, symbol, timeframe)
            signal_type = direction.upper()  # 'BUY' or 'SELL'
            result = calculator.calculate(signal_type, entry_price)

            sl = result['sl']
            tp = result['tp']

            # Validate results
            if sl <= 0 or tp <= 0:
                return {
                    'success': False,
                    'error': f'Invalid TP/SL calculated: SL={sl}, TP={tp}'
                }

            # Update trade in database
            trade.sl = sl
            trade.tp = tp
            db.commit()

            logger.info(
                f"✅ Auto TP/SL: #{trade.ticket} - SL: {sl:.5f}, TP: {tp:.5f} "
                f"(R:R {result.get('risk_reward', 'N/A'):.2f}:1)"
            )

            # Send MODIFY_POSITION command to MT5
            self._send_modify_command(trade.ticket, sl, tp, trade.account_id, db)

            return {
                'success': True,
                'sl': sl,
                'tp': tp,
                'rr_ratio': result.get('risk_reward'),
                'reason': f'Auto-calculated ({timeframe})'
            }

        except Exception as e:
            logger.error(f"Error calculating TP/SL for #{trade.ticket}: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _detect_timeframe(self, trade: Trade) -> str:
        """
        Detect appropriate timeframe for TP/SL calculation.

        For now, defaults to H4 (most common).
        Could be enhanced to detect based on trade duration, time of day, etc.

        Args:
            trade: Trade object

        Returns:
            Timeframe string (e.g., 'H4')
        """
        # Default to H4 for manual trades
        # Future enhancement: Could analyze trade age, entry time, etc.
        return 'H4'

    def _send_modify_command(self, ticket: int, sl: float, tp: float, account_id: int, db: Session):
        """
        Send MODIFY_TRADE command to MT5 EA.

        Args:
            ticket: Trade ticket
            sl: Stop Loss price
            tp: Take Profit price
            account_id: Account ID
            db: Database session
        """
        try:
            from models import Command

            # Create MODIFY_TRADE command in the format expected by EA
            command = Command(
                id=str(uuid.uuid4()),
                account_id=account_id,
                command_type='MODIFY_TRADE',
                payload={
                    'ticket': ticket,
                    'sl': sl,
                    'tp': tp
                },
                status='pending'
            )

            db.add(command)
            db.commit()

            logger.info(
                f"📤 Sent MODIFY_TRADE command for #{ticket} to MT5: SL={sl:.5f}, TP={tp:.5f}"
            )

        except Exception as e:
            logger.error(f"Error sending MODIFY command for #{ticket}: {e}", exc_info=True)

    def reset_processed_cache(self):
        """Reset the processed tickets cache (call periodically or on restart)"""
        self.processed_tickets.clear()
        logger.info("🔄 Auto TP/SL: Cleared processed tickets cache")


# Global instance
_auto_tpsl_manager = None


def get_auto_tpsl_manager() -> AutoTPSLManager:
    """Get or create the global AutoTPSLManager instance"""
    global _auto_tpsl_manager
    if _auto_tpsl_manager is None:
        _auto_tpsl_manager = AutoTPSLManager()
    return _auto_tpsl_manager
