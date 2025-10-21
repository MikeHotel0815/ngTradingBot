#!/usr/bin/env python3
"""
Regenerate all higher timeframe OHLC data from M1 candles
Run this after fixing the aggregation logic
"""

import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import OHLCData
from ohlc_aggregator import aggregate_m1_to_higher_timeframes
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database connection - use environment variable or default
import os
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://trader:tradingbot_secret_2025@postgres:5432/ngtradingbot')
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

def main():
    db = Session()

    try:
        # Get all symbols that have M1 data
        symbols = db.query(OHLCData.symbol).filter(
            OHLCData.timeframe == 'M1'
        ).distinct().all()

        logger.info(f"Found {len(symbols)} symbols with M1 data")

        for (symbol,) in symbols:
            logger.info(f"Regenerating higher timeframes for {symbol}...")

            # Get all M1 candles for this symbol (not just recent ones)
            m1_candles = db.query(OHLCData).filter(
                OHLCData.symbol == symbol,
                OHLCData.timeframe == 'M1'
            ).order_by(OHLCData.timestamp).all()

            logger.info(f"  Processing {len(m1_candles)} M1 candles")

            # Aggregate to all higher timeframes
            timeframes = {
                'M5': 5,
                'M15': 15,
                'M30': 30,
                'H1': 60,
                'H4': 240,
                'D1': 1440,
                'W1': 10080
            }

            for tf_name, minutes in timeframes.items():
                logger.info(f"  Creating {tf_name} candles...")

                groups = {}
                for candle in m1_candles:
                    # Calculate period start for this timeframe
                    if tf_name == 'W1':
                        # Week starts on Monday (weekday=0)
                        from datetime import timedelta
                        days_since_monday = candle.timestamp.weekday()
                        period_start = (candle.timestamp - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
                    elif tf_name == 'D1':
                        period_start = candle.timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
                    elif tf_name == 'H4':
                        hour_group = (candle.timestamp.hour // 4) * 4
                        period_start = candle.timestamp.replace(hour=hour_group, minute=0, second=0, microsecond=0)
                    elif tf_name == 'H1':
                        period_start = candle.timestamp.replace(minute=0, second=0, microsecond=0)
                    else:  # M5, M15, M30
                        minute_group = (candle.timestamp.minute // minutes) * minutes
                        period_start = candle.timestamp.replace(minute=minute_group, second=0, microsecond=0)

                    if period_start not in groups:
                        groups[period_start] = []
                    groups[period_start].append(candle)

                # Create higher timeframe candles
                created = 0
                skipped = 0
                for period_time, candle_group in groups.items():
                    # Check if already exists
                    existing = db.query(OHLCData).filter(
                        OHLCData.symbol == symbol,
                        OHLCData.timeframe == tf_name,
                        OHLCData.timestamp == period_time
                    ).first()

                    # Require at least 80% of expected candles
                    min_candles_required = max(1, int(minutes * 0.8))

                    if not existing and len(candle_group) >= min_candles_required:
                        ohlc = OHLCData(
                            symbol=symbol,
                            timeframe=tf_name,
                            open=candle_group[0].open,
                            high=max(c.high for c in candle_group),
                            low=min(c.low for c in candle_group),
                            close=candle_group[-1].close,
                            volume=sum(c.volume for c in candle_group),
                            timestamp=period_time
                        )
                        db.add(ohlc)
                        created += 1
                    elif not existing:
                        skipped += 1

                db.commit()
                logger.info(f"    Created {created} {tf_name} candles, skipped {skipped} incomplete periods")

        logger.info("Done! All higher timeframe candles regenerated successfully.")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

if __name__ == '__main__':
    main()
