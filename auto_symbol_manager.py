"""
Automatic Symbol Manager

Automatically pauses/resumes symbols based on performance metrics to prevent
continuous losses from problem symbols (like XAGUSD in the baseline report).

Features:
- Auto-pause symbols with win rate < 40%
- Auto-pause symbols with daily loss > configured threshold
- Auto-pause after N consecutive losses
- Auto-resume after cooldown period with improved performance
- Integration with AI Decision Log for transparency

Usage:
    # As standalone script
    python3 auto_symbol_manager.py --check-all

    # Or import and use in background worker
    from auto_symbol_manager import AutoSymbolManager
    manager = AutoSymbolManager()
    manager.evaluate_all_symbols()
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from models import (
    SymbolTradingConfig,
    Trade,
    Account,
    GlobalSettings
)
from ai_decision_log import AIDecisionLogger
from database import get_session

logger = logging.getLogger(__name__)


class AutoSymbolManager:
    """Manages automatic symbol pause/resume based on performance"""

    # Default thresholds (can be overridden by GlobalSettings or SymbolTradingConfig)
    DEFAULT_MIN_WIN_RATE = 0.40  # 40%
    DEFAULT_MAX_DAILY_LOSS = 20.0  # EUR
    DEFAULT_MAX_CONSECUTIVE_LOSSES = 5
    DEFAULT_MIN_TRADES_FOR_EVALUATION = 10  # Need at least 10 trades
    DEFAULT_COOLDOWN_HOURS = 24  # Hours before auto-resume attempt

    def __init__(self, db: Optional[Session] = None):
        """
        Initialize Auto Symbol Manager

        Args:
            db: Optional database session (if None, creates new one)
        """
        self.db = db or next(get_session())
        self.ai_logger = AIDecisionLogger(self.db)

    def evaluate_symbol(
        self,
        account_id: int,
        symbol: str,
        direction: Optional[str] = None
    ) -> Dict:
        """
        Evaluate a single symbol's performance and take action if needed

        Args:
            account_id: Account ID
            symbol: Trading symbol
            direction: Optional direction filter ('BUY' or 'SELL')

        Returns:
            Dict with evaluation results and actions taken
        """
        logger.info(f"Evaluating {symbol} {direction or 'BOTH'} for account {account_id}")

        # Get or create symbol config
        config = self.db.query(SymbolTradingConfig).filter(
            SymbolTradingConfig.account_id == account_id,
            SymbolTradingConfig.symbol == symbol,
            SymbolTradingConfig.direction == (direction or 'BOTH')
        ).first()

        if not config:
            logger.warning(f"No config found for {symbol} {direction or 'BOTH'}")
            return {'action': 'skip', 'reason': 'no_config'}

        # Get recent trades (last 30 days)
        cutoff_date = datetime.utcnow() - timedelta(days=30)

        trades_query = self.db.query(Trade).filter(
            Trade.account_id == account_id,
            Trade.symbol == symbol,
            Trade.status == 'closed',
            Trade.close_time >= cutoff_date
        )

        if direction and direction != 'BOTH':
            trades_query = trades_query.filter(Trade.direction == direction)

        recent_trades = trades_query.all()

        if len(recent_trades) < self.DEFAULT_MIN_TRADES_FOR_EVALUATION:
            logger.info(f"  Not enough trades for evaluation ({len(recent_trades)} < {self.DEFAULT_MIN_TRADES_FOR_EVALUATION})")
            return {
                'action': 'skip',
                'reason': 'insufficient_data',
                'trades_count': len(recent_trades)
            }

        # Calculate performance metrics
        winning_trades = [t for t in recent_trades if t.profit > 0]
        losing_trades = [t for t in recent_trades if t.profit <= 0]

        win_rate = len(winning_trades) / len(recent_trades) if recent_trades else 0
        total_profit = sum(t.profit for t in recent_trades)
        avg_profit = total_profit / len(recent_trades) if recent_trades else 0

        # Calculate daily loss (last 24h)
        daily_cutoff = datetime.utcnow() - timedelta(hours=24)
        daily_trades = [t for t in recent_trades if t.close_time >= daily_cutoff]
        daily_loss = sum(t.profit for t in daily_trades if t.profit < 0)

        # Check consecutive losses
        recent_trades_sorted = sorted(recent_trades, key=lambda x: x.close_time, reverse=True)
        consecutive_losses = 0
        for trade in recent_trades_sorted:
            if trade.profit <= 0:
                consecutive_losses += 1
            else:
                break

        # Determine action
        action_result = {
            'symbol': symbol,
            'direction': direction or 'BOTH',
            'trades_count': len(recent_trades),
            'win_rate': win_rate,
            'total_profit': total_profit,
            'avg_profit': avg_profit,
            'daily_loss': daily_loss,
            'consecutive_losses': consecutive_losses,
            'current_status': config.status,
            'action': 'none',
            'reason': ''
        }

        # Decision logic
        should_pause = False
        pause_reason = []

        # Check 1: Win Rate too low
        if win_rate < self.DEFAULT_MIN_WIN_RATE:
            should_pause = True
            pause_reason.append(f"Win rate {win_rate:.1%} < {self.DEFAULT_MIN_WIN_RATE:.0%}")

        # Check 2: Daily loss exceeds threshold
        if abs(daily_loss) > self.DEFAULT_MAX_DAILY_LOSS and len(daily_trades) >= 3:
            should_pause = True
            pause_reason.append(f"Daily loss €{abs(daily_loss):.2f} > €{self.DEFAULT_MAX_DAILY_LOSS}")

        # Check 3: Too many consecutive losses
        if consecutive_losses >= self.DEFAULT_MAX_CONSECUTIVE_LOSSES:
            should_pause = True
            pause_reason.append(f"{consecutive_losses} consecutive losses >= {self.DEFAULT_MAX_CONSECUTIVE_LOSSES}")

        # Take action
        if should_pause and config.status == 'active':
            # PAUSE symbol
            old_status = config.status
            config.status = 'paused'
            config.pause_reason = '; '.join(pause_reason)
            config.paused_at = datetime.utcnow()

            self.db.commit()

            action_result['action'] = 'PAUSED'
            action_result['reason'] = config.pause_reason

            # Log to AI Decision Log
            self.ai_logger.log_decision(
                account_id=account_id,
                decision_type='SYMBOL_AUTO_PAUSE',
                decision='PAUSED',
                symbol=symbol,
                direction=direction,
                primary_reason=pause_reason[0] if pause_reason else 'Performance criteria not met',
                detailed_reasoning={
                    'win_rate': f"{win_rate:.2%}",
                    'total_profit': f"€{total_profit:.2f}",
                    'daily_loss': f"€{daily_loss:.2f}",
                    'consecutive_losses': consecutive_losses,
                    'trades_evaluated': len(recent_trades),
                    'all_reasons': pause_reason
                },
                impact_level='HIGH',
                confidence_score=95.0,
                risk_score=85.0
            )

            logger.warning(f"  🚨 PAUSED {symbol} {direction or 'BOTH'}: {config.pause_reason}")

        elif not should_pause and config.status == 'paused':
            # Check if cooldown period has passed
            if config.paused_at:
                hours_paused = (datetime.utcnow() - config.paused_at).total_seconds() / 3600

                if hours_paused >= self.DEFAULT_COOLDOWN_HOURS:
                    # Performance improved, auto-resume
                    old_status = config.status
                    config.status = 'active'
                    config.pause_reason = None
                    config.paused_at = None

                    self.db.commit()

                    action_result['action'] = 'RESUMED'
                    action_result['reason'] = f"Performance improved after {hours_paused:.1f}h cooldown"

                    # Log to AI Decision Log
                    self.ai_logger.log_decision(
                        account_id=account_id,
                        decision_type='SYMBOL_AUTO_RESUME',
                        decision='RESUMED',
                        symbol=symbol,
                        direction=direction,
                        primary_reason=f"Win rate {win_rate:.1%} meets criteria",
                        detailed_reasoning={
                            'win_rate': f"{win_rate:.2%}",
                            'total_profit': f"€{total_profit:.2f}",
                            'hours_paused': f"{hours_paused:.1f}h",
                            'trades_since_pause': len(recent_trades)
                        },
                        impact_level='MEDIUM',
                        confidence_score=80.0
                    )

                    logger.info(f"  ✅ RESUMED {symbol} {direction or 'BOTH'}: {action_result['reason']}")
                else:
                    action_result['action'] = 'cooldown'
                    action_result['reason'] = f"Still in cooldown ({hours_paused:.1f}h / {self.DEFAULT_COOLDOWN_HOURS}h)"

        return action_result

    def evaluate_all_symbols(self, account_id: Optional[int] = None) -> List[Dict]:
        """
        Evaluate all symbols for all accounts (or specific account)

        Args:
            account_id: Optional specific account ID

        Returns:
            List of evaluation results for all symbols
        """
        results = []

        # Get accounts to evaluate
        if account_id:
            accounts = [self.db.query(Account).filter(Account.id == account_id).first()]
        else:
            accounts = self.db.query(Account).all()

        if not accounts:
            logger.warning("No accounts found for evaluation")
            return results

        for account in accounts:
            if not account:
                continue

            logger.info(f"\n{'='*60}")
            logger.info(f"Evaluating account {account.id} ({account.mt5_account_number})")
            logger.info(f"{'='*60}")

            # Get all symbol configs for this account
            configs = self.db.query(SymbolTradingConfig).filter(
                SymbolTradingConfig.account_id == account.id
            ).all()

            for config in configs:
                result = self.evaluate_symbol(
                    account_id=account.id,
                    symbol=config.symbol,
                    direction=config.direction
                )
                results.append(result)

        # Summary
        paused_count = sum(1 for r in results if r['action'] == 'PAUSED')
        resumed_count = sum(1 for r in results if r['action'] == 'RESUMED')

        logger.info(f"\n{'='*60}")
        logger.info(f"AUTO SYMBOL MANAGER SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"Total symbols evaluated: {len(results)}")
        logger.info(f"Paused: {paused_count}")
        logger.info(f"Resumed: {resumed_count}")
        logger.info(f"No action: {len(results) - paused_count - resumed_count}")
        logger.info(f"{'='*60}\n")

        return results

    def get_paused_symbols(self, account_id: int) -> List[Dict]:
        """
        Get list of currently paused symbols with pause reasons

        Args:
            account_id: Account ID

        Returns:
            List of paused symbol info
        """
        paused_configs = self.db.query(SymbolTradingConfig).filter(
            SymbolTradingConfig.account_id == account_id,
            SymbolTradingConfig.status == 'paused'
        ).all()

        return [
            {
                'symbol': config.symbol,
                'direction': config.direction,
                'pause_reason': config.pause_reason,
                'paused_at': config.paused_at,
                'hours_paused': (datetime.utcnow() - config.paused_at).total_seconds() / 3600 if config.paused_at else 0
            }
            for config in paused_configs
        ]

    def manual_pause(self, account_id: int, symbol: str, reason: str, direction: str = 'BOTH') -> bool:
        """
        Manually pause a symbol

        Args:
            account_id: Account ID
            symbol: Symbol to pause
            reason: Reason for pause
            direction: Direction ('BUY', 'SELL', or 'BOTH')

        Returns:
            True if successful
        """
        config = self.db.query(SymbolTradingConfig).filter(
            SymbolTradingConfig.account_id == account_id,
            SymbolTradingConfig.symbol == symbol,
            SymbolTradingConfig.direction == direction
        ).first()

        if config:
            config.status = 'paused'
            config.pause_reason = f"Manual: {reason}"
            config.paused_at = datetime.utcnow()
            self.db.commit()

            self.ai_logger.log_decision(
                account_id=account_id,
                decision_type='SYMBOL_MANUAL_PAUSE',
                decision='PAUSED',
                symbol=symbol,
                direction=direction,
                primary_reason=reason,
                impact_level='HIGH'
            )

            logger.info(f"✅ Manually paused {symbol} {direction}: {reason}")
            return True
        else:
            logger.error(f"❌ Config not found for {symbol} {direction}")
            return False

    def manual_resume(self, account_id: int, symbol: str, direction: str = 'BOTH') -> bool:
        """
        Manually resume a paused symbol

        Args:
            account_id: Account ID
            symbol: Symbol to resume
            direction: Direction ('BUY', 'SELL', or 'BOTH')

        Returns:
            True if successful
        """
        config = self.db.query(SymbolTradingConfig).filter(
            SymbolTradingConfig.account_id == account_id,
            SymbolTradingConfig.symbol == symbol,
            SymbolTradingConfig.direction == direction
        ).first()

        if config:
            config.status = 'active'
            config.pause_reason = None
            config.paused_at = None
            self.db.commit()

            self.ai_logger.log_decision(
                account_id=account_id,
                decision_type='SYMBOL_MANUAL_RESUME',
                decision='RESUMED',
                symbol=symbol,
                direction=direction,
                primary_reason='Manual resume',
                impact_level='MEDIUM'
            )

            logger.info(f"✅ Manually resumed {symbol} {direction}")
            return True
        else:
            logger.error(f"❌ Config not found for {symbol} {direction}")
            return False


def main():
    """CLI entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Auto Symbol Manager')
    parser.add_argument('--check-all', action='store_true', help='Check all symbols for all accounts')
    parser.add_argument('--account-id', type=int, help='Specific account ID')
    parser.add_argument('--list-paused', action='store_true', help='List paused symbols')
    parser.add_argument('--pause', help='Manually pause a symbol (format: SYMBOL:DIRECTION:REASON)')
    parser.add_argument('--resume', help='Manually resume a symbol (format: SYMBOL:DIRECTION)')

    args = parser.parse_args()

    manager = AutoSymbolManager()

    if args.check_all:
        results = manager.evaluate_all_symbols(account_id=args.account_id)

    elif args.list_paused:
        if not args.account_id:
            print("❌ --account-id required for --list-paused")
            return 1

        paused = manager.get_paused_symbols(args.account_id)
        print(f"\n📊 Paused Symbols (Account {args.account_id}):\n")
        print(f"{'Symbol':<10} {'Direction':<8} {'Reason':<40} {'Hours Paused':<12}")
        print("-" * 80)
        for p in paused:
            print(f"{p['symbol']:<10} {p['direction']:<8} {p['pause_reason']:<40} {p['hours_paused']:<12.1f}")

    elif args.pause:
        if not args.account_id:
            print("❌ --account-id required for --pause")
            return 1

        parts = args.pause.split(':')
        if len(parts) != 3:
            print("❌ Invalid format. Use: SYMBOL:DIRECTION:REASON")
            return 1

        symbol, direction, reason = parts
        manager.manual_pause(args.account_id, symbol, reason, direction)

    elif args.resume:
        if not args.account_id:
            print("❌ --account-id required for --resume")
            return 1

        parts = args.resume.split(':')
        if len(parts) != 2:
            print("❌ Invalid format. Use: SYMBOL:DIRECTION")
            return 1

        symbol, direction = parts
        manager.manual_resume(args.account_id, symbol, direction)

    else:
        parser.print_help()

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
