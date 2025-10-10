"""
Trade Replacement Manager - Intelligent Opportunity Cost Management

Closes old trades when better signals appear for the same symbol.
Prevents opportunity cost: Don't hold mediocre/losing trades when higher-confidence signals emerge.

Key Features:
1. Symbol-specific max hold times (prevent 18h EURUSD losses)
2. Confidence-based replacement (close old trade if new signal is significantly better)
3. Smart profit-taking (close small profits if better opportunity appears)
4. Loss-cutting acceleration (faster SL for long-running losing trades)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_
from models import Trade, TradingSignal, Command
from database import get_db

logger = logging.getLogger(__name__)


class TradeReplacementManager:
    """Manages trade replacement logic based on opportunity cost"""

    # Symbol-specific maximum hold times (hours)
    MAX_HOLD_TIMES = {
        # PROBLEM SYMBOLS (from 72h analysis)
        'EURUSD': 6.0,   # Currently averaging 11h for losses - cut to 6h max
        'USDJPY': 4.0,   # Fast-moving, should be quick

        # GOOD PERFORMERS (allow longer holds)
        'GBPUSD': 12.0,  # Averaging 5.25h, performing well
        'XAUUSD': 8.0,   # Currently 0.69h avg, 100% win rate
        'DE40.c': 8.0,   # Currently 0.25h avg, 100% win rate
        'BTCUSD': 8.0,   # Currently 2.20h avg, good performance

        # DEFAULT for other symbols
        'DEFAULT': 8.0,
    }

    # Confidence thresholds for replacement
    MIN_CONFIDENCE_IMPROVEMENT = 15.0  # New signal must be 15% better
    MIN_REPLACEMENT_CONFIDENCE = 70.0  # New signal must be at least 70%

    # Profit thresholds for early closure
    SMALL_PROFIT_THRESHOLD = 2.0  # €2 or less = "small profit"
    SMALL_LOSS_THRESHOLD = -1.0   # -€1 or better = "acceptable loss to cut"

    def __init__(self):
        logger.info("Trade Replacement Manager initialized")

    def get_max_hold_time(self, symbol: str) -> float:
        """Get maximum hold time for a symbol in hours"""
        return self.MAX_HOLD_TIMES.get(symbol, self.MAX_HOLD_TIMES['DEFAULT'])

    def check_hold_time_exceeded(self, trade: Trade) -> bool:
        """Check if trade has exceeded maximum hold time"""
        if not trade.open_time:
            return False

        max_hold_hours = self.get_max_hold_time(trade.symbol)
        hours_open = (datetime.utcnow() - trade.open_time).total_seconds() / 3600

        if hours_open > max_hold_hours:
            logger.warning(
                f"⏰ Trade {trade.ticket} ({trade.symbol}) exceeded max hold time: "
                f"{hours_open:.1f}h > {max_hold_hours}h"
            )
            return True

        return False

    def should_replace_for_better_signal(
        self,
        existing_trade: Trade,
        new_signal: TradingSignal
    ) -> Tuple[bool, Optional[str]]:
        """
        Determine if existing trade should be closed for a better signal.

        Returns:
            (should_close, reason)
        """
        # Only consider if same symbol
        if existing_trade.symbol != new_signal.symbol:
            return False, None

        # Don't replace if directions don't match signal types
        # trade.direction is 'buy' or 'sell', signal.signal_type is 'BUY' or 'SELL'
        if existing_trade.direction.upper() != new_signal.signal_type:
            return False, None

        # Get current signal confidence (if exists)
        old_confidence = getattr(existing_trade, 'entry_confidence', 0.0) or 0.0
        new_confidence = float(new_signal.confidence or 0.0)

        # Calculate confidence improvement
        confidence_delta = new_confidence - old_confidence

        # Check hold time
        hours_open = 0
        if existing_trade.open_time:
            hours_open = (datetime.utcnow() - existing_trade.open_time).total_seconds() / 3600

        # Decision logic
        trade_profit = existing_trade.profit or 0.0

        # CASE 1: Max hold time exceeded
        max_hold = self.get_max_hold_time(existing_trade.symbol)
        if hours_open > max_hold:
            return True, f"Max hold time exceeded ({hours_open:.1f}h > {max_hold}h)"

        # CASE 2: Trade in loss + new signal much better
        if trade_profit < 0 and confidence_delta >= self.MIN_CONFIDENCE_IMPROVEMENT:
            if new_confidence >= self.MIN_REPLACEMENT_CONFIDENCE:
                return True, (
                    f"Better signal available: {new_confidence:.1f}% vs {old_confidence:.1f}% "
                    f"(+{confidence_delta:.1f}%), current P&L: €{trade_profit:.2f}"
                )

        # CASE 3: Small profit + significantly better signal
        if 0 < trade_profit <= self.SMALL_PROFIT_THRESHOLD:
            if confidence_delta >= self.MIN_CONFIDENCE_IMPROVEMENT:
                if new_confidence >= self.MIN_REPLACEMENT_CONFIDENCE:
                    return True, (
                        f"Small profit (€{trade_profit:.2f}), better signal available: "
                        f"{new_confidence:.1f}% vs {old_confidence:.1f}%"
                    )

        # CASE 4: Small loss + better signal (cut losses for opportunity)
        if self.SMALL_LOSS_THRESHOLD <= trade_profit < 0:
            if confidence_delta >= self.MIN_CONFIDENCE_IMPROVEMENT:
                if new_confidence >= self.MIN_REPLACEMENT_CONFIDENCE:
                    return True, (
                        f"Small loss (€{trade_profit:.2f}), better signal available: "
                        f"{new_confidence:.1f}% vs {old_confidence:.1f}%"
                    )

        # CASE 5: Trade running too long in loss (even without better signal)
        if trade_profit < -2.0 and hours_open > (max_hold * 0.7):  # 70% of max hold time
            return True, (
                f"Loss running too long: €{trade_profit:.2f} for {hours_open:.1f}h "
                f"({hours_open/max_hold*100:.0f}% of max hold time)"
            )

        return False, None

    def find_replaceable_trades(
        self,
        db: Session,
        account_id: int,
        new_signal: TradingSignal
    ) -> List[Tuple[Trade, str]]:
        """
        Find all trades that should be closed for a new signal.

        Returns:
            List of (trade, reason) tuples
        """
        # Get open trades for this symbol
        open_trades = db.query(Trade).filter(
            and_(
                Trade.account_id == account_id,
                Trade.symbol == new_signal.symbol,
                Trade.status == 'open'
            )
        ).all()

        replaceable = []
        for trade in open_trades:
            should_close, reason = self.should_replace_for_better_signal(trade, new_signal)
            if should_close:
                replaceable.append((trade, reason))

        return replaceable

    def check_stale_trades(self, db: Session, account_id: int) -> List[Tuple[Trade, str]]:
        """
        Find trades that should be closed due to max hold time (independent of new signals).

        Returns:
            List of (trade, reason) tuples
        """
        open_trades = db.query(Trade).filter(
            and_(
                Trade.account_id == account_id,
                Trade.status == 'open'
            )
        ).all()

        stale_trades = []
        for trade in open_trades:
            if self.check_hold_time_exceeded(trade):
                hours_open = (datetime.utcnow() - trade.open_time).total_seconds() / 3600
                max_hold = self.get_max_hold_time(trade.symbol)
                profit = trade.profit or 0.0

                reason = (
                    f"Max hold time exceeded: {hours_open:.1f}h > {max_hold}h, "
                    f"P&L: €{profit:.2f}"
                )
                stale_trades.append((trade, reason))

        return stale_trades

    def create_close_command(
        self,
        db: Session,
        trade: Trade,
        reason: str,
        account_id: int
    ) -> Optional[Command]:
        """
        Create a command to close a trade.

        Args:
            db: Database session
            trade: Trade to close
            reason: Reason for closing
            account_id: Account ID

        Returns:
            Command object or None if failed
        """
        try:
            # Create close command
            command = Command(
                account_id=account_id,
                command_type='close_position',
                status='pending',
                payload={
                    'ticket': trade.ticket,
                    'symbol': trade.symbol,  # ✅ FIX: symbol goes in payload, not as direct parameter
                    'reason': f'Trade Replacement: {reason}',
                    'close_type': 'opportunity_cost'
                }
            )

            db.add(command)
            db.commit()

            logger.info(
                f"📤 Created close command for trade {trade.ticket} ({trade.symbol}): {reason}"
            )

            return command

        except Exception as e:
            logger.error(f"Error creating close command: {e}", exc_info=True)
            db.rollback()
            return None

    def process_opportunity_cost_management(
        self,
        db: Session,
        account_id: int,
        new_signal: Optional[TradingSignal] = None
    ) -> Dict:
        """
        Main entry point: Process all opportunity cost management.

        Args:
            db: Database session
            account_id: Account ID
            new_signal: Optional new signal to check against

        Returns:
            Dict with closed trades and reasons
        """
        result = {
            'trades_closed': 0,
            'reasons': [],
            'commands_created': []
        }

        try:
            trades_to_close = []

            # Check for stale trades (max hold time exceeded)
            stale_trades = self.check_stale_trades(db, account_id)
            trades_to_close.extend(stale_trades)

            # If new signal provided, check for replaceable trades
            if new_signal:
                replaceable_trades = self.find_replaceable_trades(db, account_id, new_signal)
                trades_to_close.extend(replaceable_trades)

            # Create close commands
            for trade, reason in trades_to_close:
                command = self.create_close_command(db, trade, reason, account_id)
                if command:
                    result['trades_closed'] += 1
                    result['reasons'].append(f"{trade.symbol} #{trade.ticket}: {reason}")
                    result['commands_created'].append(command.id)

            if result['trades_closed'] > 0:
                logger.info(
                    f"🔄 Opportunity Cost Manager: Closed {result['trades_closed']} trades"
                )
                for reason in result['reasons']:
                    logger.info(f"  - {reason}")

            return result

        except Exception as e:
            logger.error(f"Error in opportunity cost management: {e}", exc_info=True)
            return result


# Global instance
_trade_replacement_manager = None

def get_trade_replacement_manager() -> TradeReplacementManager:
    """Get singleton instance of TradeReplacementManager"""
    global _trade_replacement_manager
    if _trade_replacement_manager is None:
        _trade_replacement_manager = TradeReplacementManager()
    return _trade_replacement_manager
