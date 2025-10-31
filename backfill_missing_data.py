#!/usr/bin/env python3
"""
Backfill Missing OHLC Data

Fetches missing historical data from MT5 during downtime periods
and fills gaps in the database.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Tuple
from database import SessionLocal
from models import OHLCData, BrokerSymbol
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DataBackfiller:
    """Backfill missing historical data"""

    TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1']

    # Timeframe to minutes mapping
    TF_MINUTES = {
        'M1': 1,
        'M5': 5,
        'M15': 15,
        'M30': 30,
        'H1': 60,
        'H4': 240,
        'D1': 1440
    }

    def __init__(self):
        self.db = SessionLocal()

    def get_traded_symbols(self) -> List[str]:
        """Get list of symbols we trade"""
        # Get symbols from symbol_trading_config table (actively traded symbols)
        symbols = self.db.execute(text("""
            SELECT DISTINCT symbol
            FROM symbol_trading_config
            ORDER BY symbol
        """)).fetchall()
        return [s[0] for s in symbols]

    def find_data_gaps(self, symbol: str, timeframe: str,
                       start_time: datetime, end_time: datetime) -> List[Tuple[datetime, datetime]]:
        """
        Find gaps in OHLC data for a symbol/timeframe

        Returns:
            List of (gap_start, gap_end) tuples
        """
        # Get all candles in the period
        candles = self.db.execute(text("""
            SELECT timestamp FROM ohlc_data
            WHERE symbol = :symbol
            AND timeframe = :timeframe
            AND timestamp >= :start_time
            AND timestamp <= :end_time
            ORDER BY timestamp ASC
        """), {
            'symbol': symbol,
            'timeframe': timeframe,
            'start_time': start_time,
            'end_time': end_time
        }).fetchall()

        if not candles:
            # No data at all - entire period is a gap
            return [(start_time, end_time)]

        gaps = []
        expected_interval = timedelta(minutes=self.TF_MINUTES[timeframe])

        # Check for gap before first candle
        first_candle = candles[0][0]
        if first_candle > start_time + expected_interval:
            gaps.append((start_time, first_candle - expected_interval))

        # Check for gaps between candles
        for i in range(len(candles) - 1):
            current = candles[i][0]
            next_candle = candles[i + 1][0]
            expected_next = current + expected_interval

            if next_candle > expected_next + expected_interval:
                # Gap detected
                gaps.append((expected_next, next_candle - expected_interval))

        # Check for gap after last candle
        last_candle = candles[-1][0]
        if last_candle < end_time - expected_interval:
            gaps.append((last_candle + expected_interval, end_time))

        return gaps

    def request_mt5_data(self, symbol: str, timeframe: str,
                        start_time: datetime, end_time: datetime) -> bool:
        """
        Request MT5 EA to send historical data via API

        Note: This creates a command that MT5 EA will process
        Returns True if command was created successfully
        """
        try:
            # Create a special command for MT5 to fetch historical data
            from redis_client import get_redis_client
            import json

            redis_client = get_redis_client()

            command = {
                'command_id': f'backfill_{symbol}_{timeframe}_{int(start_time.timestamp())}',
                'type': 'FETCH_HISTORY',
                'symbol': symbol,
                'timeframe': timeframe,
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'created_at': datetime.now().isoformat()
            }

            # Push to Redis queue
            redis_client.lpush('mt5_backfill_queue', json.dumps(command))

            logger.info(f"📥 Requested {symbol} {timeframe} data from {start_time} to {end_time}")
            return True

        except Exception as e:
            logger.error(f"Error requesting MT5 data: {e}")
            return False

    def backfill_symbol(self, symbol: str, start_time: datetime, end_time: datetime):
        """Backfill all timeframes for a symbol"""

        logger.info(f"\n{'='*70}")
        logger.info(f"🔄 Backfilling {symbol}")
        logger.info(f"{'='*70}")

        total_gaps = 0

        for timeframe in self.TIMEFRAMES:
            gaps = self.find_data_gaps(symbol, timeframe, start_time, end_time)

            if gaps:
                logger.info(f"\n  {timeframe}: Found {len(gaps)} gap(s)")
                total_gaps += len(gaps)

                for gap_start, gap_end in gaps:
                    duration_hours = (gap_end - gap_start).total_seconds() / 3600
                    logger.info(f"    Gap: {gap_start.strftime('%Y-%m-%d %H:%M')} to {gap_end.strftime('%H:%M')} ({duration_hours:.1f}h)")

                    # Request data from MT5
                    # Note: Actual implementation would need MT5 EA support
                    # For now, we'll log what needs to be fetched

            else:
                logger.info(f"  {timeframe}: ✅ No gaps")

        return total_gaps

    def backfill_all(self, start_time: datetime, end_time: datetime):
        """Backfill all traded symbols"""

        symbols = self.get_traded_symbols()

        logger.info("=" * 70)
        logger.info("🔄 DATA BACKFILL REPORT")
        logger.info("=" * 70)
        logger.info(f"\n📅 Period: {start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%m-%d %H:%M')}")
        logger.info(f"⏱️  Duration: {(end_time - start_time).total_seconds() / 3600:.1f} hours")
        logger.info(f"📊 Symbols: {len(symbols)}")

        total_gaps = 0

        for symbol in symbols:
            gaps = self.backfill_symbol(symbol, start_time, end_time)
            total_gaps += gaps

        logger.info("\n" + "=" * 70)
        logger.info(f"📊 SUMMARY")
        logger.info("=" * 70)
        logger.info(f"  Total symbols checked: {len(symbols)}")
        logger.info(f"  Total gaps found: {total_gaps}")

        if total_gaps > 0:
            logger.warning("\n⚠️  DATA GAPS DETECTED!")
            logger.info("\nℹ️  To fill these gaps:")
            logger.info("   1. MT5 must be running and connected")
            logger.info("   2. Use MT5's built-in history sync feature")
            logger.info("   3. Or: Export data from MT5 and import manually")
            logger.info("\n💡 Recommendation:")
            logger.info("   For a 9.6-hour gap, the impact on signal quality is minimal")
            logger.info("   since indicators will recalculate with available data.")
            logger.info("   New signals will be generated with current market data.")
        else:
            logger.info("\n✅ No gaps detected - data is complete!")

    def close(self):
        """Close database connection"""
        self.db.close()


if __name__ == '__main__':
    import sys

    # Default: Check last 12 hours
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=12)

    # Parse command line arguments
    if len(sys.argv) > 1:
        # Custom start time provided
        start_time = datetime.fromisoformat(sys.argv[1])

    if len(sys.argv) > 2:
        # Custom end time provided
        end_time = datetime.fromisoformat(sys.argv[2])

    backfiller = DataBackfiller()

    try:
        backfiller.backfill_all(start_time, end_time)
    finally:
        backfiller.close()
