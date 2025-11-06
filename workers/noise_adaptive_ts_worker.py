"""
Noise-Adaptive Trailing Stop Worker
Continuously updates trailing stops for all open trades based on real-time market noise.

Update Frequency:
- Calm markets: Every 30 seconds
- Normal markets: Every 15 seconds
- Volatile markets: Every 5 seconds
"""

import logging
import time
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from database import SessionLocal
from models import Trade, Tick
from noise_adaptive_trailing_stop import NoiseAdaptiveTrailingStop

logger = logging.getLogger(__name__)


class NoiseAdaptiveTrailingStopWorker:
    """
    Background worker that updates trailing stops dynamically based on market noise.
    """

    def __init__(self, account_id: int = 3):
        self.account_id = account_id
        self.nas = NoiseAdaptiveTrailingStop(account_id=account_id)
        self.is_running = False

        # Update frequency settings (seconds)
        self.update_intervals = {
            'calm': 30,
            'normal': 15,
            'volatile': 10,
            'very_volatile': 5,
        }

        # Statistics
        self.stats = {
            'updates_processed': 0,
            'sl_updates_made': 0,
            'errors': 0,
            'last_update_time': None,
            'started_at': None,
        }

    def get_update_interval(self, volatility_classifications: list) -> int:
        """
        Determine update interval based on volatility of open trades.

        Returns interval in seconds.
        """
        if not volatility_classifications:
            return self.update_intervals['normal']

        # Find the most volatile classification
        if 'very_volatile' in volatility_classifications:
            return self.update_intervals['very_volatile']
        elif 'volatile' in volatility_classifications:
            return self.update_intervals['volatile']
        elif 'calm' in volatility_classifications:
            return self.update_intervals['calm']
        else:
            return self.update_intervals['normal']

    def process_trade(self, db, trade: Trade) -> dict:
        """
        Process a single trade's trailing stop.

        Returns:
            dict with processing results
        """
        try:
            # Get current price from latest tick
            tick = db.query(Tick).filter(
                Tick.symbol == trade.symbol
            ).order_by(Tick.timestamp.desc()).first()

            if not tick:
                logger.warning(f"Trade #{trade.ticket}: No tick data available for {trade.symbol}")
                return {
                    'success': False,
                    'error': 'no_tick_data',
                    'trade_ticket': trade.ticket,
                }

            # Determine current price based on direction
            current_price = tick.bid if trade.direction.upper() == 'BUY' else tick.ask

            # Update trailing stop
            result = self.nas.update_trailing_stop(db, trade, current_price, dry_run=False)

            if result:
                logger.info(f"✅ Trade #{trade.ticket} ({trade.symbol}): SL updated {result['old_sl']:.5f} → {result['new_sl']:.5f}")
                return {
                    'success': True,
                    'updated': True,
                    'trade_ticket': trade.ticket,
                    'result': result,
                }
            else:
                logger.debug(f"Trade #{trade.ticket} ({trade.symbol}): No SL update needed")
                return {
                    'success': True,
                    'updated': False,
                    'trade_ticket': trade.ticket,
                }

        except Exception as e:
            logger.error(f"Error processing Trade #{trade.ticket}: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'trade_ticket': trade.ticket,
            }

    def process_all_trades(self):
        """
        Process all open trades for the account.

        Returns:
            dict with processing statistics
        """
        db = SessionLocal()
        volatility_classifications = []
        updates_made = 0
        errors = 0

        try:
            # Get all open trades for this account
            open_trades = db.query(Trade).filter(
                Trade.account_id == self.account_id,
                Trade.status == 'open'
            ).all()

            if not open_trades:
                logger.debug(f"No open trades for account {self.account_id}")
                return {
                    'trades_processed': 0,
                    'updates_made': 0,
                    'errors': 0,
                    'volatility_classifications': [],
                    'update_interval': self.update_intervals['normal'],
                }

            logger.info(f"Processing {len(open_trades)} open trades...")

            for trade in open_trades:
                result = self.process_trade(db, trade)

                # Track volatility classifications for interval adjustment
                if result.get('success') and result.get('result'):
                    calc = result['result'].get('calculation', {})
                    vol_data = calc.get('analysis', {}).get('volatility', {})
                    classification = vol_data.get('classification')
                    if classification:
                        volatility_classifications.append(classification)

                # Track statistics
                if result.get('success'):
                    if result.get('updated'):
                        updates_made += 1
                else:
                    errors += 1

            # Determine next update interval based on market volatility
            update_interval = self.get_update_interval(volatility_classifications)

            return {
                'trades_processed': len(open_trades),
                'updates_made': updates_made,
                'errors': errors,
                'volatility_classifications': volatility_classifications,
                'update_interval': update_interval,
            }

        except Exception as e:
            logger.error(f"Error in process_all_trades: {str(e)}", exc_info=True)
            return {
                'trades_processed': 0,
                'updates_made': 0,
                'errors': 1,
                'volatility_classifications': [],
                'update_interval': self.update_intervals['normal'],
            }
        finally:
            db.close()

    def run(self):
        """
        Main worker loop.
        """
        self.is_running = True
        self.stats['started_at'] = datetime.utcnow()

        logger.info(f"{'='*80}")
        logger.info(f"Noise-Adaptive Trailing Stop Worker STARTED")
        logger.info(f"Account ID: {self.account_id}")
        logger.info(f"Update intervals: {self.update_intervals}")
        logger.info(f"{'='*80}")

        update_interval = self.update_intervals['normal']  # Start with normal interval

        while self.is_running:
            try:
                cycle_start = time.time()

                # Process all trades
                result = self.process_all_trades()

                # Update statistics
                self.stats['updates_processed'] += result['trades_processed']
                self.stats['sl_updates_made'] += result['updates_made']
                self.stats['errors'] += result['errors']
                self.stats['last_update_time'] = datetime.utcnow()

                # Adjust next update interval based on volatility
                update_interval = result['update_interval']

                # Log summary
                if result['trades_processed'] > 0:
                    logger.info(
                        f"Cycle complete: {result['trades_processed']} trades processed, "
                        f"{result['updates_made']} SL updates, "
                        f"{result['errors']} errors. "
                        f"Next update in {update_interval}s (volatility: {result['volatility_classifications']})"
                    )

                # Sleep until next cycle
                cycle_duration = time.time() - cycle_start
                sleep_time = max(0, update_interval - cycle_duration)

                if sleep_time > 0:
                    time.sleep(sleep_time)

            except KeyboardInterrupt:
                logger.info("Worker interrupted by user")
                self.stop()
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {str(e)}", exc_info=True)
                self.stats['errors'] += 1
                time.sleep(10)  # Sleep 10s on error before retrying

        logger.info(f"{'='*80}")
        logger.info(f"Noise-Adaptive Trailing Stop Worker STOPPED")
        logger.info(f"Total updates processed: {self.stats['updates_processed']}")
        logger.info(f"Total SL updates made: {self.stats['sl_updates_made']}")
        logger.info(f"Total errors: {self.stats['errors']}")
        logger.info(f"{'='*80}")

    def stop(self):
        """Stop the worker gracefully."""
        logger.info("Stopping worker...")
        self.is_running = False

    def get_status(self) -> dict:
        """Get current worker status and statistics."""
        uptime = None
        if self.stats['started_at']:
            uptime = (datetime.utcnow() - self.stats['started_at']).total_seconds()

        return {
            'is_running': self.is_running,
            'account_id': self.account_id,
            'stats': {
                **self.stats,
                'uptime_seconds': uptime,
            },
        }


def main():
    """
    Standalone entry point for testing.
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Get account_id from command line or use default
    account_id = int(sys.argv[1]) if len(sys.argv) > 1 else 3

    worker = NoiseAdaptiveTrailingStopWorker(account_id=account_id)

    try:
        worker.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        worker.stop()


if __name__ == '__main__':
    main()
