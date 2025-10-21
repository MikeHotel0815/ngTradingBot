#!/usr/bin/env python3
"""
Load historical OHLC data for symbols with missing data
Fetches data from MT5 and stores in database
"""

import os
import sys
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import OHLCData
import logging
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://trader:tradingbot_secret_2025@postgres:5432/ngtradingbot')
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

# MT5 Connector endpoint (adjust if needed)
MT5_API_URL = os.getenv('MT5_API_URL', 'http://host.docker.internal:5000')

def fetch_historical_data_from_mt5(symbol, timeframe, bars=1000):
    """
    Fetch historical OHLC data from MT5 connector

    Args:
        symbol: Trading symbol (e.g., 'AUDUSD')
        timeframe: MT5 timeframe (e.g., 'M1', 'H1')
        bars: Number of bars to fetch

    Returns:
        List of OHLC data dictionaries
    """
    try:
        # Map timeframes to MT5 timeframe constants
        timeframe_map = {
            'M1': 1,
            'M5': 5,
            'M15': 15,
            'M30': 30,
            'H1': 60,
            'H4': 240,
            'D1': 1440
        }

        mt5_timeframe = timeframe_map.get(timeframe, 1)

        # Call MT5 API to get historical data
        url = f"{MT5_API_URL}/api/ohlc"
        params = {
            'symbol': symbol,
            'timeframe': timeframe,
            'count': bars
        }

        logger.info(f"Fetching {bars} {timeframe} bars for {symbol} from MT5...")
        response = requests.get(url, params=params, timeout=30)

        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                return data.get('data', [])
            else:
                logger.error(f"MT5 API error: {data.get('message')}")
                return []
        else:
            logger.error(f"HTTP error {response.status_code}: {response.text}")
            return []

    except Exception as e:
        logger.error(f"Error fetching data from MT5: {e}")
        return []

def store_ohlc_data(db, symbol, timeframe, ohlc_data):
    """
    Store OHLC data in database

    Args:
        db: Database session
        symbol: Trading symbol
        timeframe: Timeframe
        ohlc_data: List of OHLC dictionaries with keys: time, open, high, low, close, volume

    Returns:
        Number of candles stored
    """
    stored = 0

    for candle in ohlc_data:
        try:
            # Parse timestamp
            if isinstance(candle['time'], str):
                timestamp = datetime.fromisoformat(candle['time'].replace('Z', '+00:00'))
            else:
                # Assume Unix timestamp
                timestamp = datetime.fromtimestamp(candle['time'])

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
        except Exception as e:
            logger.error(f"Error storing candle: {e}")
            continue

    db.commit()
    return stored

def load_historical_for_symbol(symbol, days_back=30):
    """
    Load historical data for a symbol

    Args:
        symbol: Trading symbol
        days_back: How many days of history to load
    """
    db = Session()

    try:
        logger.info(f"Loading historical data for {symbol}...")

        # Calculate how many M1 bars we need (roughly)
        # days_back * 24 hours * 60 minutes = total M1 bars
        # But markets aren't open 24/7, so we fetch more to be safe
        bars_needed = days_back * 24 * 60

        # Start with M1 data (most granular)
        logger.info(f"  Fetching M1 data ({bars_needed} bars)...")
        m1_data = fetch_historical_data_from_mt5(symbol, 'M1', bars_needed)

        if m1_data:
            stored = store_ohlc_data(db, symbol, 'M1', m1_data)
            logger.info(f"  ✅ Stored {stored} M1 candles")

            # Now aggregate to higher timeframes using our aggregator
            logger.info(f"  Aggregating to higher timeframes...")
            from ohlc_aggregator import aggregate_m1_to_higher_timeframes
            aggregate_m1_to_higher_timeframes(db, None, symbol)
            logger.info(f"  ✅ Higher timeframes created")

        else:
            logger.warning(f"  ⚠️ No M1 data received from MT5 for {symbol}")

    except Exception as e:
        logger.error(f"Error loading historical data for {symbol}: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

def main():
    """Main function to load historical data for missing symbols"""

    # Symbols that need historical data
    symbols = ['AUDUSD', 'US500.c', 'XAGUSD']

    logger.info(f"Starting historical data load for {len(symbols)} symbols...")

    for symbol in symbols:
        load_historical_for_symbol(symbol, days_back=30)

    logger.info("✅ Historical data load completed!")

if __name__ == '__main__':
    main()
