#!/usr/bin/env python3
"""
Seed missing symbols with basic OHLC data
For symbols that have no tick stream, create minimal M1 data so they can display charts
"""

import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import OHLCData
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://trader:tradingbot_secret_2025@postgres:5432/ngtradingbot')
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

# Typical price ranges for the symbols (for realistic fake data)
SYMBOL_PRICES = {
    'AUDUSD': 0.6500,  # Australian Dollar around 0.65
    'US500.c': 5800.0,  # S&P 500 around 5800
    'XAGUSD': 31.50    # Silver around $31.50
}

def create_sample_m1_data(db, symbol, base_price, days=30):
    """
    Create sample M1 OHLC data for a symbol

    Args:
        db: Database session
        symbol: Trading symbol
        base_price: Base price to use
        days: Number of days of data to create
    """
    import random

    logger.info(f"Creating {days} days of M1 data for {symbol}...")

    # Start from 30 days ago
    start_time = datetime.utcnow() - timedelta(days=days)
    current_time = start_time

    # Track current price (random walk)
    current_price = base_price
    created = 0

    # Create M1 candles for each minute
    while current_time < datetime.utcnow():
        # Skip weekends for forex (Saturday 00:00 to Sunday 21:00 UTC)
        if symbol in ['AUDUSD', 'XAGUSD']:
            if current_time.weekday() == 5 or (current_time.weekday() == 6 and current_time.hour < 21):
                current_time += timedelta(minutes=1)
                continue

        # Check if candle already exists
        existing = db.query(OHLCData).filter(
            OHLCData.symbol == symbol,
            OHLCData.timeframe == 'M1',
            OHLCData.timestamp == current_time
        ).first()

        if not existing:
            # Random price movement (+/- 0.1%)
            price_change_pct = random.uniform(-0.001, 0.001)
            price_change = current_price * price_change_pct

            open_price = current_price
            close_price = current_price + price_change

            # High/Low with some variance
            high_price = max(open_price, close_price) * (1 + random.uniform(0, 0.0005))
            low_price = min(open_price, close_price) * (1 - random.uniform(0, 0.0005))

            # Create M1 candle
            ohlc = OHLCData(
                symbol=symbol,
                timeframe='M1',
                timestamp=current_time,
                open=round(open_price, 5),
                high=round(high_price, 5),
                low=round(low_price, 5),
                close=round(close_price, 5),
                volume=random.randint(10, 100)
            )

            db.add(ohlc)
            created += 1

            # Update current price for next candle
            current_price = close_price

            # Commit in batches of 1000
            if created % 1000 == 0:
                db.commit()
                logger.info(f"  Created {created} M1 candles...")

        current_time += timedelta(minutes=1)

    db.commit()
    logger.info(f"  ✅ Created {created} M1 candles for {symbol}")
    return created

def main():
    """Create sample data for missing symbols"""

    db = Session()

    try:
        for symbol, base_price in SYMBOL_PRICES.items():
            logger.info(f"\nProcessing {symbol}...")

            # Create M1 data
            create_sample_m1_data(db, symbol, base_price, days=30)

            # Aggregate to higher timeframes
            logger.info(f"  Aggregating to higher timeframes...")
            from ohlc_aggregator import aggregate_m1_to_higher_timeframes
            aggregate_m1_to_higher_timeframes(db, None, symbol)
            logger.info(f"  ✅ Higher timeframes created for {symbol}")

        logger.info("\n✅ All symbols seeded successfully!")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

if __name__ == '__main__':
    main()
