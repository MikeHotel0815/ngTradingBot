#!/usr/bin/env python3
"""
Send command to MT5 connector to fetch historical data for symbols
"""

import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Command
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://trader:tradingbot_secret_2025@postgres:5432/ngtradingbot')
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

def send_fetch_history_command(symbol, days=30):
    """
    Send command to MT5 connector to fetch historical data

    Args:
        symbol: Trading symbol
        days: Number of days of history to fetch
    """
    db = Session()

    try:
        # Create command for MT5 connector
        command = Command(
            command_type='FETCH_HISTORY',
            symbol=symbol,
            params={
                'days': days,
                'timeframes': ['M1']  # Fetch M1, we'll aggregate the rest
            },
            status='pending',
            created_at=datetime.utcnow()
        )

        db.add(command)
        db.commit()

        logger.info(f"✅ Command sent to MT5 connector: Fetch {days} days of history for {symbol}")
        logger.info(f"   Command ID: {command.id}")

        return command.id

    except Exception as e:
        logger.error(f"Error sending command: {e}")
        db.rollback()
        return None
    finally:
        db.close()

def main():
    """Send fetch history commands for missing symbols"""

    symbols = ['AUDUSD', 'US500.c', 'XAGUSD']

    logger.info(f"Sending fetch history commands for {len(symbols)} symbols...")

    for symbol in symbols:
        command_id = send_fetch_history_command(symbol, days=30)
        if command_id:
            logger.info(f"  {symbol}: Command #{command_id} created")
        else:
            logger.error(f"  {symbol}: Failed to create command")

    logger.info("\n⚠️  NOTE: The MT5 connector needs to process these commands.")
    logger.info("Check the MT5 connector logs to see if it supports FETCH_HISTORY commands.")

if __name__ == '__main__':
    main()
