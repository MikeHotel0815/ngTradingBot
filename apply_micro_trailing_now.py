#!/usr/bin/env python3
"""
Apply Micro-Trailing NOW - No prompts, just do it
For immediate application on all open trades
"""

import os
os.environ['DATABASE_URL'] = 'postgresql://trader:tradingbot_secret_2025@postgres:5432/ngtradingbot'

from micro_trailing_manager import apply_micro_trailing_to_all
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    logger.info("🔥 Applying Micro-Trailing to ALL open trades...")
    stats = apply_micro_trailing_to_all()
    logger.info(f"✅ Done! {stats['trailed']}/{stats['total_trades']} trades adjusted")
