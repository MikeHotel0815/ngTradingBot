#!/usr/bin/env python3
"""
Import Historical Data for ML Training

This script imports 1-2 years of historical OHLC data using the existing
load_historical_ohlc.py logic but optimized for ML training requirements.

Usage:
    # Inside Docker container:
    docker exec -it ngtradingbot_server python3 import_historical_for_ml.py

    # Or with custom parameters:
    docker exec -it ngtradingbot_server python3 import_historical_for_ml.py --days 365 --symbols EURUSD XAUUSD

Requirements:
    - MT5 EA must be running and connected
    - Database must be accessible
    - Sufficient disk space (~200-500 MB for 1 year data)
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import OHLCData
import logging
import requests
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database connection
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://trader:tradingbot_secret_2025@localhost:9904/ngtradingbot'
)
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

# MT5 API endpoint (local Flask server)
MT5_API_URL = os.getenv('MT5_API_URL', 'http://localhost:9905')


def fetch_ohlc_from_mt5_api(symbol, timeframe, count=10000):
    """
    Fetch historical OHLC data from MT5 via the Flask API

    Args:
        symbol: Trading symbol (e.g., 'EURUSD')
        timeframe: Timeframe string (e.g., 'M5', 'H1')
        count: Number of bars to fetch

    Returns:
        List of OHLC dictionaries or None if failed
    """
    try:
        # Build API endpoint
        # The Flask app might have an endpoint like /api/historical_data
        # If not, we'll need to create one

        url = f"{MT5_API_URL}/api/historical_ohlc"
        params = {
            'symbol': symbol,
            'timeframe': timeframe,
            'count': count
        }

        logger.info(f"📥 Fetching {count} {timeframe} bars for {symbol} from MT5 API...")
        response = requests.get(url, params=params, timeout=60)

        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success' and 'data' in data:
                return data['data']
            else:
                logger.warning(f"API returned status: {data.get('status')}, message: {data.get('message')}")
                return None
        else:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return None


def store_ohlc_batch(db, symbol, timeframe, ohlc_data):
    """
    Store OHLC data in database (batch insert)

    Args:
        db: Database session
        symbol: Trading symbol
        timeframe: Timeframe
        ohlc_data: List of OHLC dictionaries

    Returns:
        Number of candles stored
    """
    if not ohlc_data:
        return 0

    stored = 0
    skipped = 0

    for candle in ohlc_data:
        try:
            # Parse timestamp
            if isinstance(candle['time'], str):
                # ISO format
                timestamp = datetime.fromisoformat(candle['time'].replace('Z', '+00:00'))
            elif isinstance(candle['time'], (int, float)):
                # Unix timestamp
                timestamp = datetime.fromtimestamp(candle['time'])
            else:
                timestamp = candle['time']

            # Check if candle already exists
            existing = db.query(OHLCData).filter(
                OHLCData.symbol == symbol,
                OHLCData.timeframe == timeframe,
                OHLCData.timestamp == timestamp
            ).first()

            if not existing:
                ohlc = OHLCData(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=timestamp,
                    open=float(candle['open']),
                    high=float(candle['high']),
                    low=float(candle['low']),
                    close=float(candle['close']),
                    volume=int(candle.get('volume', 0))
                )
                db.add(ohlc)
                stored += 1

                # Commit in batches to avoid memory issues
                if stored % 1000 == 0:
                    db.commit()
                    logger.info(f"    💾 Committed {stored} candles so far...")
            else:
                skipped += 1

        except Exception as e:
            logger.error(f"Error storing candle: {e}")
            continue

    # Final commit
    db.commit()

    logger.info(f"    ✅ Stored {stored} new candles, skipped {skipped} duplicates")
    return stored


def import_historical_data(
    symbols,
    timeframes,
    days_back=365,
    bars_per_request=10000
):
    """
    Import historical data for specified symbols and timeframes

    Args:
        symbols: List of symbols to import
        timeframes: List of timeframes to import
        days_back: How many days of history to import
        bars_per_request: Maximum bars per API request
    """
    db = Session()

    stats = {
        'total_symbols': len(symbols),
        'total_timeframes': len(timeframes),
        'successful': 0,
        'failed': 0,
        'total_candles': 0,
        'start_time': datetime.now()
    }

    try:
        logger.info(f"\n{'='*60}")
        logger.info(f"🚀 HISTORICAL DATA IMPORT FOR ML TRAINING")
        logger.info(f"{'='*60}")
        logger.info(f"Symbols: {', '.join(symbols)}")
        logger.info(f"Timeframes: {', '.join(timeframes)}")
        logger.info(f"Days back: {days_back}")
        logger.info(f"Target date range: {datetime.now() - timedelta(days=days_back)} → {datetime.now()}")
        logger.info(f"{'='*60}\n")

        for symbol in symbols:
            for timeframe in timeframes:
                logger.info(f"\n📊 Processing {symbol} {timeframe}")
                logger.info(f"{'─'*60}")

                # Calculate required bars based on timeframe and days
                timeframe_minutes = {
                    'M1': 1, 'M5': 5, 'M15': 15, 'M30': 30,
                    'H1': 60, 'H4': 240, 'D1': 1440
                }

                minutes = timeframe_minutes.get(timeframe, 5)
                bars_needed = int((days_back * 24 * 60) / minutes)

                # Cap at reasonable maximum (MT5 has limits)
                bars_needed = min(bars_needed, bars_per_request)

                logger.info(f"  Requesting {bars_needed} bars")

                # Fetch data from MT5 API
                ohlc_data = fetch_ohlc_from_mt5_api(symbol, timeframe, bars_needed)

                if ohlc_data:
                    logger.info(f"  📥 Received {len(ohlc_data)} bars from API")

                    # Store in database
                    candles_stored = store_ohlc_batch(db, symbol, timeframe, ohlc_data)

                    stats['successful'] += 1
                    stats['total_candles'] += candles_stored

                    logger.info(f"  ✅ Import complete for {symbol} {timeframe}")
                else:
                    logger.warning(f"  ❌ Failed to fetch data for {symbol} {timeframe}")
                    stats['failed'] += 1

                # Small delay to avoid overwhelming the API
                time.sleep(0.5)

        # Final summary
        duration = (datetime.now() - stats['start_time']).total_seconds()

        logger.info(f"\n{'='*60}")
        logger.info(f"📊 IMPORT SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"✅ Successful: {stats['successful']}/{stats['total_symbols'] * stats['total_timeframes']}")
        logger.info(f"❌ Failed: {stats['failed']}")
        logger.info(f"💾 Total candles imported: {stats['total_candles']:,}")
        logger.info(f"⏱️  Duration: {duration:.1f} seconds")
        logger.info(f"{'='*60}\n")

        if stats['total_candles'] > 0:
            logger.info(f"🎉 SUCCESS! Historical data ready for ML training")
            logger.info(f"   You can now proceed with Phase 1 (XGBoost) implementation")
        else:
            logger.warning(f"⚠️  WARNING: No data imported!")
            logger.warning(f"   Please check:")
            logger.warning(f"   1. MT5 EA is running and connected")
            logger.warning(f"   2. Flask API endpoint /api/historical_ohlc exists")
            logger.warning(f"   3. Network connectivity to MT5")

    except Exception as e:
        logger.error(f"Fatal error during import: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

    return stats


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Import historical OHLC data for ML training'
    )
    parser.add_argument(
        '--symbols',
        nargs='+',
        default=['EURUSD', 'XAUUSD', 'US500.c', 'BTCUSD', 'GBPUSD', 'AUDUSD'],
        help='Symbols to import (default: EURUSD XAUUSD US500.c BTCUSD GBPUSD AUDUSD)'
    )
    parser.add_argument(
        '--timeframes',
        nargs='+',
        default=['M5', 'M15', 'H1', 'H4', 'D1'],
        help='Timeframes to import (default: M5 M15 H1 H4 D1)'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=365,
        help='Days of history to import (default: 365 = 1 year)'
    )
    parser.add_argument(
        '--bars',
        type=int,
        default=10000,
        help='Maximum bars per request (default: 10000)'
    )

    args = parser.parse_args()

    # Execute import
    stats = import_historical_data(
        symbols=args.symbols,
        timeframes=args.timeframes,
        days_back=args.days,
        bars_per_request=args.bars
    )

    # Exit code based on success
    sys.exit(0 if stats['total_candles'] > 0 else 1)


if __name__ == '__main__':
    main()
