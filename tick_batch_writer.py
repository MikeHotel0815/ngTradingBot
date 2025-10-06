"""
Tick Batch Writer - Background worker that writes buffered ticks from Redis to PostgreSQL
"""

import time
import logging
from datetime import datetime
from threading import Thread
from redis_client import get_redis
from database import ScopedSession
from models import Tick

logger = logging.getLogger(__name__)

class TickBatchWriter:
    def __init__(self, interval=5, batch_size=1000):
        """
        Initialize Tick Batch Writer

        Args:
            interval: Write interval in seconds (default: 5)
            batch_size: Max ticks per write batch (default: 1000)
        """
        self.interval = interval
        self.batch_size = batch_size
        self.running = False
        self.thread = None
        self.redis = None
        self.total_written = 0
        self.total_batches = 0

    def start(self):
        """Start the background worker"""
        if self.running:
            logger.warning("Tick batch writer already running")
            return

        self.running = True
        self.redis = get_redis()
        self.thread = Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        logger.info(f"Tick batch writer started (interval={self.interval}s, batch_size={self.batch_size})")

    def stop(self):
        """Stop the background worker"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=10)
        logger.info(f"Tick batch writer stopped (wrote {self.total_written} ticks in {self.total_batches} batches)")

    def _worker_loop(self):
        """Main worker loop"""
        while self.running:
            try:
                self._write_batch()
            except Exception as e:
                logger.error(f"Tick batch writer error: {e}", exc_info=True)

            # Sleep for interval
            time.sleep(self.interval)

    def _write_batch(self):
        """Write one batch of ticks from Redis to PostgreSQL"""
        db = ScopedSession()

        try:
            # Get all accounts with buffered ticks
            all_accounts = self._get_accounts_with_buffers()

            if not all_accounts:
                return

            total_ticks = 0

            for account_id in all_accounts:
                # Get all buffered ticks for this account
                buffers = self.redis.get_all_buffers(account_id, clear=True)

                if not buffers:
                    continue

                tick_objects = []

                # Convert buffered ticks to Tick objects
                for symbol, ticks in buffers.items():
                    for tick_data in ticks:
                        # Convert timestamp
                        timestamp = tick_data.get('timestamp')
                        if isinstance(timestamp, (int, float)):
                            timestamp = datetime.fromtimestamp(timestamp)
                        elif timestamp is None:
                            timestamp = datetime.utcnow()

                        tick = Tick(
                            account_id=tick_data.get('account_id', account_id),
                            symbol=tick_data.get('symbol'),
                            bid=tick_data.get('bid'),
                            ask=tick_data.get('ask'),
                            spread=tick_data.get('spread'),
                            volume=tick_data.get('volume', 0),
                            timestamp=timestamp,
                            tradeable=tick_data.get('tradeable', True)
                        )
                        tick_objects.append(tick)

                        # Batch size limit
                        if len(tick_objects) >= self.batch_size:
                            db.bulk_save_objects(tick_objects)
                            db.commit()
                            total_ticks += len(tick_objects)
                            tick_objects = []

                # Write remaining ticks
                if tick_objects:
                    db.bulk_save_objects(tick_objects)
                    db.commit()
                    total_ticks += len(tick_objects)

            if total_ticks > 0:
                self.total_written += total_ticks
                self.total_batches += 1
                logger.info(f"Batch write: {total_ticks} ticks written to PostgreSQL (total: {self.total_written})")

        except Exception as e:
            logger.error(f"Batch write failed: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()

    def _get_accounts_with_buffers(self):
        """Get list of account IDs that have buffered ticks"""
        try:
            # Get all buffer keys
            pattern = "ticks:buffer:*"
            keys = self.redis.client.keys(pattern)

            # Extract unique account IDs
            accounts = set()
            for key in keys:
                # Key format: ticks:buffer:{account_id}:{symbol}
                parts = key.split(':')
                if len(parts) >= 3:
                    try:
                        account_id = int(parts[2])
                        accounts.add(account_id)
                    except ValueError:
                        continue

            return list(accounts)

        except Exception as e:
            logger.error(f"Failed to get accounts with buffers: {e}")
            return []

    def get_stats(self):
        """Get batch writer statistics"""
        return {
            'running': self.running,
            'interval': self.interval,
            'batch_size': self.batch_size,
            'total_written': self.total_written,
            'total_batches': self.total_batches,
            'avg_per_batch': self.total_written / self.total_batches if self.total_batches > 0 else 0
        }


# Global instance
_batch_writer = None

def get_batch_writer():
    """Get global batch writer instance"""
    global _batch_writer
    if _batch_writer is None:
        _batch_writer = TickBatchWriter(interval=5, batch_size=1000)
    return _batch_writer

def start_batch_writer(interval=5, batch_size=1000):
    """Start the global batch writer"""
    writer = get_batch_writer()
    writer.interval = interval
    writer.batch_size = batch_size
    writer.start()
    return writer
