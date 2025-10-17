#!/usr/bin/env python3
import os
os.environ['DATABASE_URL'] = 'postgresql://trader:tradingbot_secret_2025@postgres:5432/ngtradingbot'

from unified_trailing_final import apply_trailing_now
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

if __name__ == '__main__':
    print("\n🔥 Applying UNIFIED TRAILING STOP with TP Extension...\n")
    stats = apply_trailing_now()
    print(f"\n✅ DONE!")
    print(f"   - Trades processed: {stats['total']}")
    print(f"   - SL trailed: {stats['trailed']}")
    print(f"   - TP extended: {stats['extended']}")
    print(f"   - Errors: {stats['errors']}\n")
