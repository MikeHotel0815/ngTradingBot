"""
Historical OHLC Data Manager

Handles downloading, storing and retrieving historical data for backtesting.
Uses TimescaleDB for efficient time-series storage.

Strategy:
1. Download from MT5 (primary source)
2. Fallback: Download from Dukascopy (free, good quality)
3. Store in PostgreSQL with TimescaleDB hypertables
4. Automatic compression for data older than 7 days
"""

import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from sqlalchemy import create_engine, text
from database import get_db_connection
import MetaTrader5 as mt5
import requests
from io import BytesIO

logger = logging.getLogger(__name__)


class HistoricalDataManager:
    """Manages historical OHLC data for backtesting"""

    # Supported timeframes
    TIMEFRAMES = {
        'M1': 1,
        'M5': 5,
        'M15': 15,
        'M30': 30,
        'H1': 60,
        'H4': 240,
        'D1': 1440
    }

    # Priority symbols for download
    PRIORITY_SYMBOLS = [
        'EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'BTCUSD', 'DE40.c'
    ]

    def __init__(self):
        self.engine = create_engine(
            "postgresql://trader:trader@localhost:9904/ngtradingbot"
        )
        self._ensure_tables_exist()

    def _ensure_tables_exist(self):
        """Create historical_ohlc table with TimescaleDB hypertable"""

        with self.engine.connect() as conn:
            # Create table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS historical_ohlc (
                    time TIMESTAMPTZ NOT NULL,
                    symbol VARCHAR(20) NOT NULL,
                    timeframe VARCHAR(10) NOT NULL,
                    open NUMERIC(18, 5) NOT NULL,
                    high NUMERIC(18, 5) NOT NULL,
                    low NUMERIC(18, 5) NOT NULL,
                    close NUMERIC(18, 5) NOT NULL,
                    volume BIGINT NOT NULL,
                    tick_volume BIGINT,
                    spread INTEGER,
                    real_volume BIGINT,
                    PRIMARY KEY (time, symbol, timeframe)
                );
            """))
            conn.commit()

            # Try to create hypertable (will fail if already exists - that's OK)
            try:
                conn.execute(text("""
                    SELECT create_hypertable(
                        'historical_ohlc',
                        'time',
                        if_not_exists => TRUE
                    );
                """))
                conn.commit()
                logger.info("✅ Created TimescaleDB hypertable for historical_ohlc")
            except Exception as e:
                # Already exists or TimescaleDB not available
                logger.debug(f"Hypertable creation skipped: {e}")

            # Create indices for fast queries
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_historical_symbol_timeframe
                ON historical_ohlc (symbol, timeframe, time DESC);
            """))
            conn.commit()

            # Enable compression (data older than 7 days)
            try:
                conn.execute(text("""
                    ALTER TABLE historical_ohlc SET (
                        timescaledb.compress,
                        timescaledb.compress_segmentby = 'symbol, timeframe'
                    );
                """))

                conn.execute(text("""
                    SELECT add_compression_policy(
                        'historical_ohlc',
                        INTERVAL '7 days',
                        if_not_exists => TRUE
                    );
                """))
                conn.commit()
                logger.info("✅ Enabled compression for historical_ohlc")
            except Exception as e:
                logger.debug(f"Compression setup skipped: {e}")

    def download_from_mt5(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Download historical data from MT5

        Args:
            symbol: Symbol name (e.g., 'EURUSD')
            timeframe: Timeframe (e.g., 'H1', 'D1')
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with OHLC data or None if failed
        """

        if timeframe not in self.TIMEFRAMES:
            logger.error(f"Invalid timeframe: {timeframe}")
            return None

        try:
            # MT5 timeframe constant
            tf_map = {
                'M1': mt5.TIMEFRAME_M1,
                'M5': mt5.TIMEFRAME_M5,
                'M15': mt5.TIMEFRAME_M15,
                'M30': mt5.TIMEFRAME_M30,
                'H1': mt5.TIMEFRAME_H1,
                'H4': mt5.TIMEFRAME_H4,
                'D1': mt5.TIMEFRAME_D1
            }

            # Initialize MT5 if not already
            if not mt5.initialize():
                logger.error("MT5 initialization failed")
                return None

            # Download data
            rates = mt5.copy_rates_range(
                symbol,
                tf_map[timeframe],
                start_date,
                end_date
            )

            if rates is None or len(rates) == 0:
                logger.warning(f"No data from MT5 for {symbol} {timeframe}")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df['symbol'] = symbol
            df['timeframe'] = timeframe

            # Rename columns to match our schema
            df = df.rename(columns={
                'tick_volume': 'tick_volume',
                'real_volume': 'real_volume'
            })

            logger.info(f"✅ Downloaded {len(df)} bars from MT5: {symbol} {timeframe}")
            return df[['time', 'symbol', 'timeframe', 'open', 'high', 'low', 'close',
                      'volume', 'tick_volume', 'spread', 'real_volume']]

        except Exception as e:
            logger.error(f"Error downloading from MT5: {e}")
            return None

    def download_from_dukascopy(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Download historical data from Dukascopy (fallback)

        Dukascopy provides free historical data for Forex pairs.
        Format: https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YEAR}/{MONTH}/{DAY}/{HOUR}h_ticks.bi5

        Args:
            symbol: Symbol name (e.g., 'EURUSD')
            timeframe: Timeframe (e.g., 'H1', 'D1')
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with OHLC data or None if failed
        """

        logger.info(f"📥 Downloading from Dukascopy: {symbol} {timeframe}")

        # Dukascopy only supports Forex pairs
        forex_pairs = ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'USDCAD', 'NZDUSD']

        if symbol not in forex_pairs:
            logger.warning(f"Dukascopy doesn't support {symbol}, only Forex pairs")
            return None

        # TODO: Implement Dukascopy download
        # This requires bi5 decompression and tick aggregation
        # For now, return None and rely on MT5

        logger.warning("Dukascopy download not yet implemented - use MT5 as primary source")
        return None

    def store_data(self, df: pd.DataFrame) -> int:
        """
        Store OHLC data in database

        Args:
            df: DataFrame with OHLC data

        Returns:
            Number of rows inserted
        """

        if df is None or len(df) == 0:
            return 0

        try:
            # Use ON CONFLICT to handle duplicates
            df.to_sql(
                'historical_ohlc',
                self.engine,
                if_exists='append',
                index=False,
                method='multi'
            )

            logger.info(f"✅ Stored {len(df)} rows in database")
            return len(df)

        except Exception as e:
            logger.error(f"Error storing data: {e}")
            return 0

    def get_data(
        self,
        symbol: str,
        timeframe: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Retrieve historical OHLC data from database

        Args:
            symbol: Symbol name
            timeframe: Timeframe
            start_date: Optional start date
            end_date: Optional end date
            limit: Optional limit on number of bars

        Returns:
            DataFrame with OHLC data
        """

        query = """
            SELECT time, open, high, low, close, volume, tick_volume, spread
            FROM historical_ohlc
            WHERE symbol = :symbol AND timeframe = :timeframe
        """

        params = {'symbol': symbol, 'timeframe': timeframe}

        if start_date:
            query += " AND time >= :start_date"
            params['start_date'] = start_date

        if end_date:
            query += " AND time <= :end_date"
            params['end_date'] = end_date

        query += " ORDER BY time ASC"

        if limit:
            query += f" LIMIT {limit}"

        df = pd.read_sql(query, self.engine, params=params)

        if len(df) > 0:
            df['time'] = pd.to_datetime(df['time'])
            df.set_index('time', inplace=True)

        return df

    def get_data_coverage(self, symbol: str, timeframe: str) -> Dict:
        """
        Get information about data coverage for a symbol/timeframe

        Returns:
            Dict with coverage info (first_date, last_date, total_bars, gaps)
        """

        query = """
            SELECT
                MIN(time) as first_date,
                MAX(time) as last_date,
                COUNT(*) as total_bars
            FROM historical_ohlc
            WHERE symbol = :symbol AND timeframe = :timeframe
        """

        with self.engine.connect() as conn:
            result = conn.execute(text(query), {'symbol': symbol, 'timeframe': timeframe}).fetchone()

            if result and result[0]:
                return {
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'first_date': result[0],
                    'last_date': result[1],
                    'total_bars': result[2],
                    'coverage_days': (result[1] - result[0]).days if result[1] and result[0] else 0
                }
            else:
                return {
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'first_date': None,
                    'last_date': None,
                    'total_bars': 0,
                    'coverage_days': 0
                }

    def download_and_store_batch(
        self,
        symbols: List[str],
        timeframes: List[str],
        years: int = 2
    ) -> Dict:
        """
        Download and store historical data for multiple symbols and timeframes

        Args:
            symbols: List of symbols
            timeframes: List of timeframes
            years: Number of years to download (default: 2)

        Returns:
            Dict with download statistics
        """

        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=years * 365)

        stats = {
            'total_symbols': len(symbols),
            'total_timeframes': len(timeframes),
            'downloaded': 0,
            'failed': 0,
            'total_bars': 0
        }

        for symbol in symbols:
            for timeframe in timeframes:
                logger.info(f"📥 Processing {symbol} {timeframe}...")

                # Try MT5 first
                df = self.download_from_mt5(symbol, timeframe, start_date, end_date)

                # Fallback to Dukascopy if MT5 fails
                if df is None or len(df) == 0:
                    df = self.download_from_dukascopy(symbol, timeframe, start_date, end_date)

                if df is not None and len(df) > 0:
                    rows = self.store_data(df)
                    stats['downloaded'] += 1
                    stats['total_bars'] += rows
                else:
                    stats['failed'] += 1
                    logger.warning(f"❌ Failed to download {symbol} {timeframe}")

        logger.info(f"✅ Batch download complete: {stats}")
        return stats


# CLI Tool for data management
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Historical Data Manager')
    parser.add_argument('--download', action='store_true', help='Download historical data')
    parser.add_argument('--symbols', nargs='+', help='Symbols to download')
    parser.add_argument('--timeframes', nargs='+', help='Timeframes to download')
    parser.add_argument('--years', type=int, default=2, help='Years of data (default: 2)')
    parser.add_argument('--coverage', action='store_true', help='Show data coverage')

    args = parser.parse_args()

    manager = HistoricalDataManager()

    if args.download:
        symbols = args.symbols or manager.PRIORITY_SYMBOLS
        timeframes = args.timeframes or ['M15', 'H1', 'H4', 'D1']

        print(f"📥 Downloading {args.years} years of data for:")
        print(f"   Symbols: {symbols}")
        print(f"   Timeframes: {timeframes}")

        stats = manager.download_and_store_batch(symbols, timeframes, args.years)

        print(f"\n✅ Download complete!")
        print(f"   Downloaded: {stats['downloaded']}/{stats['total_symbols'] * stats['total_timeframes']}")
        print(f"   Total bars: {stats['total_bars']:,}")
        print(f"   Failed: {stats['failed']}")

    elif args.coverage:
        symbols = args.symbols or manager.PRIORITY_SYMBOLS
        timeframes = args.timeframes or ['M15', 'H1', 'H4', 'D1']

        print(f"\n📊 Data Coverage Report:\n")
        print(f"{'Symbol':<10} {'TF':<5} {'First Date':<20} {'Last Date':<20} {'Bars':<10} {'Days':<8}")
        print("-" * 80)

        for symbol in symbols:
            for tf in timeframes:
                cov = manager.get_data_coverage(symbol, tf)
                first = cov['first_date'].strftime('%Y-%m-%d %H:%M') if cov['first_date'] else 'N/A'
                last = cov['last_date'].strftime('%Y-%m-%d %H:%M') if cov['last_date'] else 'N/A'

                print(f"{symbol:<10} {tf:<5} {first:<20} {last:<20} {cov['total_bars']:<10,} {cov['coverage_days']:<8}")
